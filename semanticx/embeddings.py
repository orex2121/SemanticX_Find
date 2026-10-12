from typing import Protocol
import gc,hashlib,tempfile,threading
from pathlib import Path
import numpy as np
from .paths import ROOT,atomic_json,read_json
MODEL_ID='google/embeddinggemma-2'
class EmbeddingProvider(Protocol):
 identity:dict
 def encode(self,texts,query=False):...
 def encode_images(self,images):...
class LexicalProvider:
 identity={'model':'lexical-only','revision':'1','dimension':0}
 def encode(self,texts,query=False):return [None for _ in texts]
 def encode_images(self,images):raise RuntimeError('Install and select EmbeddingGemma 2 for visual search.')
class GemmaProvider:
 def __init__(self,dimension=256,device='auto',batch_size=128,vision=False):
  self.path=ROOT/'models/embeddinggemma-2';self.vision=vision;manifest=read_json(self.path/'verified.json',{})
  if not manifest.get('revision'):raise RuntimeError('Model is not verified. Download or verify it first.')
  self.identity={'model':MODEL_ID,'revision':manifest['revision'],'dimension':dimension};self.device_choice=device;self.batch_size=batch_size;self.model=None;self.lock=threading.RLock();self.backend='Not loaded'
 def load(self):
  if self.model is not None:return
  import torch
  from sentence_transformers import SentenceTransformer
  device=('cuda' if torch.cuda.is_available() else 'cpu') if self.device_choice=='auto' else self.device_choice
  if device=='cuda' and not torch.cuda.is_available():raise RuntimeError('CUDA unavailable. Select CPU.')
  dtype=torch.bfloat16 if device=='cuda' and torch.cuda.is_bf16_supported() else torch.float32;configs={'audio_config':None}
  if not self.vision:configs['vision_config']=None
  try:self.model=SentenceTransformer(str(self.path),device=device,local_files_only=True,trust_remote_code=False,config_kwargs=configs,model_kwargs={'torch_dtype':dtype})
  except Exception as e:raise RuntimeError(f'Cannot load EmbeddingGemma 2: {e}. Check runtime versions; for CUDA failures select CPU.') from e
  self.backend=f'{torch.cuda.get_device_name() if device=="cuda" else "CPU"} — {device.upper()} — {str(dtype).split(".")[-1]}'
 def _encode(self,values):
  with self.lock:
   self.load();size=self.batch_size;result=[];pos=0
   import torch
   while pos<len(values):
    try:
     v=self.model.encode(values[pos:pos+size],batch_size=size,normalize_embeddings=True,truncate_dim=self.identity['dimension'],convert_to_numpy=True,show_progress_bar=False,prompt='');v=np.asarray(v,dtype=np.float32)
     if v.ndim!=2 or v.shape[1]!=self.identity['dimension'] or not np.isfinite(v).all():raise RuntimeError('Invalid embeddings; index not updated.')
     result.extend(v);pos+=size
    except torch.cuda.OutOfMemoryError:
     if size<=1:raise RuntimeError('CUDA memory exhausted. Select CPU.')
     size=max(1,size//2);torch.cuda.empty_cache()
   return result
 def encode(self,texts,query=False):return self._encode([('task: search result | query: '+s) if query else s for s in texts])
 def encode_images(self,images):
  if not self.vision:raise RuntimeError('Enable vision to search images.')
  # TorchVision's path decoder rejects animated WebP files.  Embeddings only
  # need one representative image, so decode the first frame with Pillow and
  # hand the model a temporary PNG.  Static images keep the zero-copy path.
  temporary_root=ROOT/'temp';temporary_root.mkdir(parents=True,exist_ok=True)
  with tempfile.TemporaryDirectory(prefix='vision-',dir=temporary_root) as directory:
   prepared=[]
   for number,value in enumerate(images):
    path=Path(value)
    if path.suffix.casefold()=='.webp':
     from PIL import Image,ImageOps
     with Image.open(path) as image:
      if getattr(image,'is_animated',False) or getattr(image,'n_frames',1)>1:
       image.seek(0);target=Path(directory)/f'{number}.png';ImageOps.exif_transpose(image).convert('RGB').save(target,'PNG');path=target
    prepared.append({'image':str(path)})
   return self._encode(prepared)
 def unload(self):
  with self.lock:
   model=self.model;self.model=None;self.backend='Not loaded'
  if model is not None:del model
  gc.collect()
  try:
   import torch
   if torch.cuda.is_available():torch.cuda.empty_cache()
  except Exception:pass
class ImageQueryAnalyzer(Protocol):
 def analyze(self,image)->str:...
class NullImageAnalyzer:
 def analyze(self,image):return ''
class ModelManager:
 path=ROOT/'models/embeddinggemma-2'
 def status(self):
  manifest=read_json(self.path/'download_manifest.json',{});verified=read_json(self.path/'verified.json',{});entries=manifest.get('files',[]);present=0;installed=0;expected=0
  for entry in entries:
   path=self.path/entry['path'];size=entry.get('size');expected+=size or 0
   if path.is_file():
    actual=path.stat().st_size;installed+=actual
    if size is None or actual==size:present+=1
  return dict(ready=bool(entries) and present==len(entries) and verified.get('revision')==manifest.get('revision'),files=present,total=len(entries),installed_bytes=installed,expected_bytes=expected,revision=manifest.get('revision',''))
 @staticmethod
 def valid(path,entry):
  if not path.is_file() or (entry['size'] is not None and path.stat().st_size!=entry['size']):return False
  h=hashlib.sha256() if entry.get('sha256') else hashlib.sha1()
  if not entry.get('sha256'):h.update(('blob '+str(path.stat().st_size)+'\0').encode())
  with path.open('rb') as f:
   for block in iter(lambda:f.read(4*1024*1024),b''):h.update(block)
  expected=entry.get('sha256') or entry.get('git_blob_sha1');return expected is None or h.hexdigest()==expected
 def download(self,progress=lambda s:None,control=None):
  import os,time,urllib.request
  from huggingface_hub import HfApi,hf_hub_url
  from filelock import FileLock
  def check():
   if control:control.check()
  check();info=HfApi().model_info(MODEL_ID,files_metadata=True);revision=info.sha;self.path.mkdir(parents=True,exist_ok=True)
  with FileLock(str(self.path/'download.lock'),timeout=0):
   entries=[]
   for sibling in info.siblings:
    name=sibling.rfilename
    if not name.endswith(('.json','.safetensors','.model','.txt','.jinja','.md')) and not name.startswith('LICENSE'):continue
    path=self.path/name
    if not path.resolve().is_relative_to(self.path.resolve()):raise ValueError('Invalid upstream path')
    lfs=sibling.lfs;expected=(lfs.get('sha256') if isinstance(lfs,dict) else getattr(lfs,'sha256',None)) if lfs else None
    entries.append(dict(path=name,size=sibling.size,sha256=expected,git_blob_sha1=None if lfs else sibling.blob_id))
   prior=read_json(self.path/'download_manifest.json',{});atomic_json(self.path/'download_manifest.json',dict(revision=revision,files=entries));(self.path/'verified.json').unlink(missing_ok=True)
   for entry in entries:
    check();target=self.path/entry['path'];target.parent.mkdir(parents=True,exist_ok=True)
    if target.is_file() and self.valid(target,entry):continue
    partial=target.with_name(target.name+'.part')
    if prior.get('revision')!=revision:partial.unlink(missing_ok=True)
    offset=partial.stat().st_size if partial.exists() else 0
    if entry['size'] is not None and offset>=entry['size']:partial.unlink();offset=0
    headers={'User-Agent':'SemanticXFind/0.1'}
    if os.environ.get('HF_TOKEN'):headers['Authorization']='Bearer '+os.environ['HF_TOKEN']
    if offset:headers['Range']=f'bytes={offset}-'
    request=urllib.request.Request(hf_hub_url(MODEL_ID,entry['path'],revision=revision),headers=headers);started=time.monotonic();last=0;received=0
    with urllib.request.urlopen(request,timeout=30) as response:
     resumed=offset>0 and response.status==206
     if resumed and not response.headers.get('Content-Range','').startswith(f'bytes {offset}-'):raise RuntimeError('Invalid Range response')
     if not resumed:offset=0
     with partial.open('ab' if resumed else 'wb') as output:
      while True:
       check();block=response.read(1024*1024)
       if not block:break
       output.write(block);received+=len(block);elapsed=time.monotonic()-started
       if elapsed-last>.4:progress(dict(file=entry['path'],downloaded=offset+received,total=entry['size'],mb_per_second=round(received/max(elapsed,.01)/1048576,2)));last=elapsed
    if not self.valid(partial,entry):partial.unlink(missing_ok=True);raise RuntimeError('Download verification failed: '+entry['path'])
    os.replace(partial,target)
   self.verify(progress,control)
 def verify(self,progress=lambda s:None,control=None):
  manifest=read_json(self.path/'download_manifest.json',{});(self.path/'verified.json').unlink(missing_ok=True)
  if not manifest.get('files'):raise RuntimeError('No download manifest. Download the model first.')
  for required in ('config.json','modules.json','tokenizer_config.json'):
   if not any(e['path']==required for e in manifest['files']):raise RuntimeError('Missing manifest entry: '+required)
  if not any(e['path'].endswith('.safetensors') for e in manifest['files']):raise RuntimeError('Checkpoint missing.')
  for entry in manifest['files']:
   if control:control.check()
   progress('Verifying '+entry['path'])
   if not self.valid(self.path/entry['path'],entry):raise RuntimeError('Missing/corrupt model file: '+entry['path'])
  atomic_json(self.path/'verified.json',dict(revision=manifest['revision']));progress('Verified: '+manifest['revision'])
