import json,os,shutil,time
from pathlib import Path
import pytest
from PIL import Image,PngImagePlugin
from semanticx.engine import Index,register,JobControl,Cancelled,IncompatibleIndex,scan,score_signals
from semanticx.extractors import workflows,slices,CHUNK_UNITS,extract
from semanticx import embeddings
@pytest.fixture
def cat(tmp_path):
 root=tmp_path/'данные';root.mkdir();return register(root,extensions=['.json','.png','.py'])
def graph(kind='UltimateSDUpscale'):
 return {'nodes':[{'id':1,'type':'UNETLoader','widgets_values':['qwen_2.1.safetensors']},{'id':2,'type':kind}],'links':[[1,1,0,2,0,'MODEL']]}
def test_token_aware_chunks_prefer_semantic_boundaries_and_overlap():
 text=('alpha '*250)+'.\n\n'+('beta '*250)+'.';parts=list(slices(text))
 assert len(parts)>=2 and parts[0].endswith('.') and 'alpha' in parts[1] and 'beta' in parts[1]
 assert all(len(CHUNK_UNITS.findall(part))<=384 for part in parts)
 long_parts=list(slices('x'*20000));assert len(long_parts)>1 and max(map(len,long_parts))<=6144
def write(cat,name='opaque.json',kind='UltimateSDUpscale'):
 path=Path(cat.root)/name;path.write_text(json.dumps(graph(kind)));return path
def test_incremental(cat):
 path=write(cat);idx=Index(cat);assert idx.run()['processed']==1;assert idx.run()['skipped']==1;assert idx.search('тайловый апскейл')[0]['path']==str(path);path.unlink();assert idx.run()['deleted']==1;assert not idx.files()
def test_bad_replacement_removes_stale(cat):
 path=write(cat);idx=Index(cat);idx.run();path.write_text('{bad');assert idx.run()['errors']==1;assert not idx.search('upscale')
def test_duplicate_detection_uses_content_hash(cat):
 first=write(cat,'first.json');second=Path(cat.root)/'second.json';second.write_bytes(first.read_bytes());write(cat,'unique.json','VAEDecodeTiled');idx=Index(cat);idx.run();duplicates=idx.duplicates()
 assert [x['relative_path'] for x in duplicates]==['first.json','second.json'] and all(x['copies']==2 for x in duplicates)
def test_modified_time_and_size_filters(cat):
 old=write(cat,'old-large.json');old.write_text(old.read_text()+' '*2000);stamp=time.time()-10*86400;os.utime(old,(stamp,stamp));recent=write(cat,'recent-small.json');idx=Index(cat);idx.run();middle=(old.stat().st_size+recent.stat().st_size)//2
 assert [Path(x['path']).name for x in idx.search('upscale',max_size_bytes=middle)]==['recent-small.json']
 assert [Path(x['path']).name for x in idx.search('upscale',modified_after_ns=time.time_ns()-86400*10**9)]==['recent-small.json']
 assert idx.search('upscale')[0]['size'] and idx.search('upscale')[0]['mtime_ns']
def test_multiple_extension_filter(cat):
 write(cat,'workflow.json');python=Path(cat.root)/'workflow.py';python.write_text('def upscale():\n return "tile"\n');idx=Index(cat);idx.run()
 assert {Path(row['path']).suffix for row in idx.search('upscale',extensions=['.json','.py'])}=={'.json','.py'}
 assert [Path(row['path']).suffix for row in idx.search('upscale',extensions=['.py'])]==['.py']
 assert not idx.search('upscale',extensions=[])
def test_png_workflow(cat):
 meta=PngImagePlugin.PngInfo();meta.add_text('workflow',json.dumps(graph()));Image.new('RGB',(8,8)).save(Path(cat.root)/'a.png',pnginfo=meta);idx=Index(cat);idx.run();assert idx.search('qwen tiled')[0]['channel']=='png_workflow';assert idx.run()['skipped']==1
def test_ocr_signal(cat):
 write(cat);idx=Index(cat);idx.run();assert idx.search('',ocr_text='UltimateSDUpscale tile width')[0]['signals']['ocr']>0
def test_cancel(cat):
 write(cat);idx=Index(cat);idx.run();control=JobControl();control.cancel()
 with pytest.raises(Cancelled):idx.run(control=control)
 assert idx.search('upscale')
def test_offline_does_not_purge(cat):
 write(cat);idx=Index(cat);idx.run();original=cat.root;cat.root+='missing'
 with pytest.raises(FileNotFoundError):idx.run()
 cat.root=original;assert len(idx.files())==1
def test_case_masks_and_exclusions(cat):
 write(cat,'HELLO.JSON');write(cat,'x.backup.json');cat.include=['hello.*'];assert [r for _,r in scan(cat)]==['HELLO.JSON']
def test_api_and_subgraphs():
 records=workflows({'1':{'class_type':'MysteryNode','inputs':{}},'2':{'class_type':'VAEDecodeTiled','inputs':{'samples':['1',0]}}},'test');assert any('MysteryNode -> VAEDecodeTiled' in c.text for c in records)
 records=workflows({'nodes':[],'definitions':{'subgraphs':[dict(graph(),id='sub1')]}},'test');assert any(c.locator.get('node')=='sub1:2' for c in records)
def test_source_never_executes(cat):
 (Path(cat.root)/'danger.py').write_text('raise RuntimeError("not executed")\ndef example():\n return 1\n');idx=Index(cat);assert idx.run()['errors']==0;assert idx.search('example')
def test_downloaded_real_workflows(cat):
 fixtures=Path(__file__).parent/'fixtures'
 for p in fixtures.glob('*.json'):
  if p.name!='SOURCES.json':shutil.copy(p,cat.root)
 idx=Index(cat);r=idx.run();assert r['processed']==4 and r['errors']==0;assert Path(idx.search('tiled upscale')[0]['path']).name=='clarity_upscale.json';assert Path(idx.search('Qwen image editing')[0]['path']).name=='qwen_edit.json'
def test_model_hash(tmp_path):
 import hashlib
 from semanticx.embeddings import ModelManager
 p=tmp_path/'file';p.write_bytes(b'hello');entry={'size':5,'sha256':hashlib.sha256(b'hello').hexdigest()};assert ModelManager.valid(p,entry);p.write_bytes(b'wrong');assert not ModelManager.valid(p,entry)
def test_model_and_ocr_status(tmp_path,monkeypatch):
 from semanticx.embeddings import ModelManager
 from semanticx.ocr import OCRManager
 model=tmp_path/'gemma';model.mkdir();monkeypatch.setattr(ModelManager,'path',model);(model/'weights.safetensors').write_bytes(b'1234');(model/'download_manifest.json').write_text(json.dumps({'revision':'rev1','files':[{'path':'weights.safetensors','size':4}]}));(model/'verified.json').write_text(json.dumps({'revision':'rev1'}));status=ModelManager().status()
 assert status['ready'] and status['files']==status['total']==1 and status['installed_bytes']==4
 ocr=tmp_path/'ocr';ocr.mkdir();monkeypatch.setattr(OCRManager,'path',ocr);files=[]
 for role in ('Det','Cls','Rec'):(ocr/f'{role}.onnx').write_bytes(role.encode());files.append({'role':role,'file':f'{role}.onnx'})
 (ocr/'manifest.json').write_text(json.dumps({'params':{'Rec.lang_type':'cyrillic'},'files':files}));status=OCRManager().status()
 assert status['ready'] and status['files']==3 and status['profile']=='cyrillic'
def test_gemma_provider_unload_releases_model_reference():
 import threading
 from semanticx.embeddings import GemmaProvider
 provider=GemmaProvider.__new__(GemmaProvider);provider.lock=threading.RLock();provider.model=object();provider.backend='CUDA'
 provider.unload();assert provider.model is None and provider.backend=='Not loaded'
def test_model_compatibility(cat):
 write(cat);idx=Index(cat);assert idx.state()['status']=='missing';idx.run();assert idx.state()['status']=='compatible'
 class Other:
  identity={'model':'TEST','revision':'1','dimension':4}
 assert Index(cat,Other()).state()['status']=='incompatible' and 'provider' in Index(cat,Other()).state()['differences']
 with pytest.raises(IncompatibleIndex):Index(cat,Other()).search('hello')

def test_filename_substring_independent_of_text(cat):
 path=write(cat,'shot-take123.json');idx=Index(cat);idx.run()
 assert idx.search('take12',ranking='filename')[0]['path']==str(path)
 assert idx.search('take12')[0]['path']==str(path)
 assert not idx.search('take12',ranking='lexical')
 assert not idx.search('upscale',ranking='filename')
 with pytest.raises(ValueError):idx.search('upscale',ranking='unknown')
def test_literal_name_filters(cat):
 write(cat);idx=Index(cat);idx.run()
 assert idx.search('upscale',node='UltimateSDUpscale',model='qwen_2.1')
 assert not idx.search('upscale',node='%')
 assert not idx.search('upscale',model='qwen_2%')
def test_png_metadata_and_pixels_have_separate_vector_cache(cat):
 import numpy as np
 class CountingProvider:
  identity={'model':'test-cache-only','dimension':2,'revision':'test'}
  vision=True
  def __init__(self):self.texts=[];self.images=[]
  def encode(self,values,query=False):self.texts.extend(values);return np.tile([1.,0.],(len(values),1))
  def encode_images(self,values):self.images.extend(values);return np.tile([0.,1.],(len(values),1))
 p=Path(cat.root)/'a.png';cat.visual=True;provider=CountingProvider();idx=Index(cat,provider)
 def png(color,kind):
  meta=PngImagePlugin.PngInfo();meta.add_text('workflow',json.dumps(graph(kind)));Image.new('RGB',(8,8),color).save(p,pnginfo=meta)
 png('red','UltimateSDUpscale');idx.run();text_count=len(provider.texts);assert len(provider.images)==1
 png('red','VAEDecodeTiled');idx.run();assert len(provider.images)==1 and len(provider.texts)>text_count
 text_count=len(provider.texts);png('blue','VAEDecodeTiled');idx.run();assert len(provider.images)==2 and len(provider.texts)==text_count
 # Test vectors validate cache plumbing only; they are not semantic quality evidence.

def test_indexer_batches_images_and_text_across_files(cat):
 import numpy as np
 class BatchProvider:
  identity={'model':'test-global-batches','dimension':2,'revision':'test'}
  vision=True
  def __init__(self):self.text_batches=[];self.image_batches=[]
  def encode(self,values,query=False):self.text_batches.append(list(values));return np.tile([1.,0.],(len(values),1))
  def encode_images(self,values):self.image_batches.append(list(values));return np.tile([0.,1.],(len(values),1))
 cat.visual=True;provider=BatchProvider()
 for number in range(6):Image.new('RGB',(8,8),(number,0,0)).save(Path(cat.root)/f'{number}.png')
 result=Index(cat,provider).run(workers=4,queue_size=16)
 assert result['processed']==6 and [len(batch) for batch in provider.image_batches]==[6] and [len(batch) for batch in provider.text_batches]==[6]

def test_animated_webp_is_converted_to_a_temporary_first_frame(tmp_path,monkeypatch):
 first=Image.new('RGB',(8,8),'red');second=Image.new('RGB',(8,8),'blue');source=tmp_path/'animated.webp';first.save(source,save_all=True,append_images=[second],duration=50,loop=0,format='WEBP')
 monkeypatch.setattr(embeddings,'ROOT',tmp_path);provider=object.__new__(embeddings.GemmaProvider);provider.vision=True;seen=[]
 def fake_encode(values):
  path=Path(values[0]['image']);seen.append(path);assert path.suffix=='.png' and path.is_file();return [[1.,0.]]
 provider._encode=fake_encode;assert provider.encode_images([source])==[[1.,0.]] and not seen[0].exists()

def test_one_bad_visual_file_does_not_stop_the_index_batch(cat):
 import numpy as np
 class ResilientProvider:
  identity={'model':'test-resilient-images','dimension':2,'revision':'test'}
  vision=True
  def encode(self,values,query=False):return np.tile([1.,0.],(len(values),1))
  def encode_images(self,values):
   if any(Path(value).name=='bad.png' for value in values):raise RuntimeError('unsupported image')
   return np.tile([0.,1.],(len(values),1))
 cat.visual=True
 for name,color in [('good-a.png','red'),('bad.png','blue'),('good-b.png','green')]:Image.new('RGB',(8,8),color).save(Path(cat.root)/name)
 result=Index(cat,ResilientProvider()).run(workers=2,queue_size=8)
 assert result['processed']==2 and result['errors']==1
 states={row['relative_path']:row['status'] for row in Index(cat,ResilientProvider()).files()};assert states=={'bad.png':'error','good-a.png':'ready','good-b.png':'ready'}

def test_visual_configuration_rejected_before_rebuild(cat):
 write(cat);idx=Index(cat);idx.run();cat.visual=True
 with pytest.raises(ValueError,match='vision-enabled'):idx.run(rebuild=True)
 cat.visual=False;assert idx.search('upscale')

def test_text_and_vision_sources_are_isolated(cat):
 import numpy as np
 class SourceProvider:
  identity={'model':'test-source-modes','dimension':2,'revision':'test'}
  vision=True
  def encode(self,values,query=False):return np.tile([1.,0.],(len(values),1))
  def encode_images(self,values):return np.tile([0.,1.],(len(values),1))
 path=Path(cat.root)/'source.png';meta=PngImagePlugin.PngInfo();meta.add_text('workflow',json.dumps(graph()));Image.new('RGB',(8,8),'blue').save(path,pnginfo=meta);cat.visual=True;idx=Index(cat,SourceProvider());idx.run()
 text=idx.search('upscale',source='text');vision=idx.search('',image_paths=[path],source='vision')
 assert text and text[0]['channel']!='visual' and 'visual' not in text[0]['signals']
 assert vision and vision[0]['channel']=='visual' and vision[0]['signals']=={'visual':1.0}
 assert not idx.search('upscale',source='vision')
 with pytest.raises(ValueError,match='search source'):idx.search('upscale',source='unknown')

def test_extended_file_types_extract_without_errors(tmp_path):
 html=tmp_path/'page.html';html.write_text('<html><body><h1>Visible heading</h1><p>Useful text</p></body></html>',encoding='utf-8');records=extract(html);assert 'Visible heading' in records[0].text and '<h1>' not in records[0].text
 pdf=tmp_path/'manual.pdf';pdf.write_bytes(b'%PDF-1.4\n');records=extract(pdf);assert records[0].kind=='pdf' and 'manual.pdf' in records[0].text
 for suffix,format_name in (('.jpg','JPEG'),('.webp','WEBP')):
  image=tmp_path/('picture'+suffix);Image.new('RGB',(8,8),'green').save(image,format=format_name);records=extract(image);assert records[0].kind=='image' and image.name in records[0].text

def test_semantic_hybrid_does_not_let_generic_note_terms_override_intent():
 # Observed scores from the real EmbeddingGemma smoke test. The generation
 # workflow has the better semantic match; generic Qwen/image terms in an edit
 # workflow note must not reverse that order.
 edit={'filename':.25,'lexical':1.,'semantic':.797051,'entities':.5,'structure':.5}
 generation={'filename':.25,'lexical':.857143,'semantic':.810996,'entities':.5,'structure':.25}
 assert score_signals(generation,semantic_enabled=True)>score_signals(edit,semantic_enabled=True)
 # Lexical-only installations retain the previous hybrid behavior.
 assert score_signals(edit,semantic_enabled=False)>score_signals(generation,semantic_enabled=False)

def test_ocr_runtime_params_support_cyrillic():
 pytest.importorskip('rapidocr')
 from semanticx.ocr import runtime_params
 params=runtime_params({'Det.ocr_version':'PP-OCRv4','Det.model_type':'mobile','Rec.ocr_version':'PP-OCRv4','Rec.model_type':'mobile','Rec.lang_type':'cyrillic'})
 assert params['Rec.lang_type'].value=='cyrillic'

def test_start_batch_relaunches_minimized():
 text=(Path(__file__).resolve().parents[1]/'Start.bat').read_text(encoding='utf-8').casefold()
 assert 'start "" /min "%comspec%"' in text
 assert '--minimized' in text
