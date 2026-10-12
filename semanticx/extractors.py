"""Recovered from recorded development commands; indexed inputs are never executed."""
from dataclasses import dataclass,field
from html.parser import HTMLParser
import ast,json,re
from pathlib import Path
from PIL import Image
VERSION='6-token-aware'
@dataclass
class Chunk:
 kind:str
 title:str
 text:str
 locator:dict=field(default_factory=dict)
 channel:str='text'
RULES={
 'UltimateSDUpscale':['upscale','tiled'],'UltimateSDUpscaleNoUpscale':['upscale','tiled'],
 'ImageUpscaleWithModel':['upscale'],'UpscaleModelLoader':['upscale model'],
 'ImageScale':['resize'],'ImageScaleBy':['resize'],'LatentUpscale':['latent upscale'],
 'VAEDecodeTiled':['tiled','vae decode'],'VAEEncodeTiled':['tiled','vae encode'],
 'LoadImage':['image input'],'SaveImage':['save image'],'KSampler':['diffusion sampling'],
 'KSamplerAdvanced':['diffusion sampling'],'ControlNetApply':['controlnet'],'ControlNetApplyAdvanced':['controlnet'],
 'ControlNetLoader':['controlnet model'],'OpenposePreprocessor':['openpose','pose control'],'DWPreprocessor':['openpose','pose control'],
 'FaceDetailer':['face restoration','detailer'],'LoraLoader':['lora'],
 'SUPIR_Upscale':['supir','upscale'],'SUPIR_sample':['supir','upscale'],'SUPIR_sample_tiled':['supir','upscale','tiled'],
 'SUPIR_encode':['supir'],'SUPIR_decode':['supir'],'SUPIR_model_loader_v2':['supir'],
 'TiledDiffusion':['tiled','diffusion sampling'],'CLIPTextEncode':['text conditioning'],
 'TextEncodeQwenImageEdit':['qwen','image editing'],'TextEncodeQwenImageEditPlus':['qwen','image editing']}
ALIASES={'апскейл':'upscale','апскейла':'upscale','увеличение':'upscale','увеличить':'upscale','тайловый':'tiled','тайлового':'tiled','тайлами':'tiled','плитками':'tiled','тайлы':'tiled','поза':'openpose','позы':'openpose','скелет':'openpose','лицо':'face restoration','лица':'face restoration','восстановление':'restoration','редактирование':'editing','изображения':'image','картинки':'image','tile':'tiled','tiling':'tiled','qwen21':'qwen 2.1'}
STOP=set('where did i use find with and the a an of for workflow workflows где я использовал найти с и для в на схема схемы'.split())
def tokens(text):return [part for w in re.findall(r'[\w]+(?:[.][\d]+)*',str(text).casefold()) for part in ALIASES.get(w,w).split() if part not in STOP]
def normalized(text):return ' '.join(tokens(text))
def dump(value):return json.dumps(value,ensure_ascii=False,separators=(',',':'))
CHUNK_UNITS=re.compile(r'\w{1,16}|[^\w\s]',re.UNICODE)
class HTMLText(HTMLParser):
 def __init__(self):super().__init__();self.parts=[]
 def handle_data(self,data):
  if data.strip():self.parts.append(data.strip())
def slices(text,target=384,overlap=56):
 text=str(text);units=list(CHUNK_UNITS.finditer(text))
 if not units:
  if text.strip():yield text.strip()
  return
 start=0
 while start<len(units):
  end=min(len(units),start+target)
  if end<len(units):
   half=units[start+target//2].start();limit=units[end-1].end();region=text[half:limit];candidates=[]
   for separator in ('\n\n','\n'):
    position=region.rfind(separator)
    if position>=0:candidates.append(half+position+len(separator))
   sentences=list(re.finditer(r'[.!?](?:\s+|$)',region))
   if sentences:candidates.append(half+sentences[-1].end())
   if candidates:
    boundary=max(candidates)
    for index in range(end-1,start,-1):
     if units[index].end()<=boundary:end=index+1;break
  begin_char=units[start].start();end_char=units[end-1].end();part=text[begin_char:end_char].strip()
  if part:yield part
  if end==len(units):break
  start=max(start+1,end-overlap)
def parse_graph(data):
 if not isinstance(data,dict):return None
 if isinstance(data.get('nodes'),list):return data
 if isinstance(data.get('prompt'),dict):return parse_graph(data['prompt'])
 nodes=[];links=[]
 for key,node in data.items():
  if not isinstance(node,dict) or 'class_type' not in node:continue
  values={}
  for name,value in node.get('inputs',{}).items():
   if isinstance(value,list) and len(value)==2 and str(value[0]) in data and isinstance(value[1],int):links.append([len(links),str(value[0]),value[1],str(key),name,'API'])
   else:values[name]=value
  nodes.append(dict(id=str(key),type=node['class_type'],title=node.get('_meta',{}).get('title',''),widgets_values=values,mode=0))
 return dict(nodes=nodes,links=links,groups=[]) if nodes else None
def workflows(data,title,channel='workflow',prefix=''):
 graph=parse_graph(data)
 if graph is None:return []
 nodes={str(n.get('id',i)):n for i,n in enumerate(graph['nodes']) if isinstance(n,dict)};capabilities=set();models=set();lines=[];chunks=[];edges=[]
 for link in graph.get('links',[]):
  if isinstance(link,list) and len(link)>=4:a,b=str(link[1]),str(link[3])
  elif isinstance(link,dict):a,b=str(link.get('origin_id')),str(link.get('target_id'))
  else:continue
  if a in nodes and b in nodes:edges.append((a,b))
 for ident,node in nodes.items():
  kind=str(node.get('type','Unknown'));state='active' if node.get('mode',0)==0 else 'bypassed' if node.get('mode')==4 else 'muted';values=dump(node.get('widgets_values',node.get('inputs',{})));facts=RULES.get(kind,[]) if state=='active' else [];capabilities.update(facts)
  if kind not in ('Note','MarkdownNote') and state=='active':models.update(re.findall(r'[^\s"\[\],]+\.(?:safetensors|ckpt|gguf|pth|pt|bin)',values,re.I))
  text=f'Node {ident}: {kind}. Title: {node.get("title","")}. State: {state}. Operations: {", ".join(facts)}. Parameters: {values}. Properties: {dump(node.get("properties",{}))}'
  neighbors=[nodes[b].get('type','?') for a,b in edges if a==ident]+[nodes[a].get('type','?') for a,b in edges if b==ident];text+='\nConnected nodes: '+', '.join(neighbors);lines.append(f'{ident}: {kind} ({state})')
  for i,part in enumerate(slices(text)):chunks.append(Chunk('node',f'{title} · {kind}',part,{'node':prefix+ident,'part':i,'operations':facts},channel))
 overview=f'ComfyUI workflow: {title}\nModels: {", ".join(sorted(models))}\nDetected operations: {", ".join(sorted(capabilities))}\nNode inventory:\n'+'\n'.join(lines)
 for i,part in enumerate(slices(overview)):chunks.insert(i,Chunk('overview',title,part,{'models':sorted(models),'operations':sorted(capabilities)},channel))
 for a,b in edges:
  if nodes[a].get('mode',0)==0 and nodes[b].get('mode',0)==0:chunks.append(Chunk('connection',title,f'Connected pipeline: {nodes[a].get("type")} -> {nodes[b].get("type")}',{'nodes':[prefix+a,prefix+b]},channel))
 for group in graph.get('groups',[]):
  if not isinstance(group,dict):continue
  bound=group.get('bounding',[]);members=[]
  if isinstance(bound,list) and len(bound)>=4:
   x,y,w,h=bound[:4]
   for ident,node in nodes.items():
    p=node.get('pos',[])
    if isinstance(p,list) and len(p)>=2 and x<=p[0]<=x+w and y<=p[1]<=y+h:members.append(ident)
  content='Group: '+str(group.get('title',''))+'\n'+'\n'.join(f'{i}: {nodes[i].get("type")} {dump(nodes[i].get("widgets_values",[]))}' for i in members)
  for part in slices(content):chunks.append(Chunk('group',title,part,{'nodes':[prefix+i for i in members]},channel))
 for sub in graph.get('definitions',{}).get('subgraphs',[]):
  if isinstance(sub,dict):chunks.extend(workflows(sub,title+' / '+str(sub.get('name','subgraph')),channel,prefix+str(sub.get('id',''))+':'))
 return chunks
def extract(path):
 path=Path(path);ext=path.suffix.lower();title=path.name
 if ext in ('.png','.jpg','.jpeg','.webp'):
  records=[];errors=[]
  with Image.open(path) as image:
   if ext=='.png':
    for key in ('workflow','prompt'):
     raw=image.info.get(key)
     if raw:
      try:records.extend(workflows(json.loads(raw) if isinstance(raw,str) else raw,title,'png_workflow'))
      except (ValueError,TypeError,KeyError) as e:errors.append(f'Invalid PNG {key}: {type(e).__name__}')
   if errors:records.append(Chunk('metadata_error',title,'; '.join(errors),{},'metadata'))
  if not records:records.append(Chunk('image',title,'Image file: '+title,{},'metadata'))
  return records
 if ext=='.pdf':
  try:
   from pypdf import PdfReader
   text='\n'.join(page.extract_text() or '' for page in PdfReader(str(path)).pages)
  except ImportError:text='PDF document: '+title
  return [Chunk('pdf',title,part,{'text_extracted':not text.startswith('PDF document:')}) for part in slices(text)]
 raw=path.read_text(encoding='utf-8-sig',errors='strict')
 if ext in ('.html','.htm'):
  parser=HTMLText();parser.feed(raw);raw=' '.join(parser.parts)
 if ext=='.json':
  data=json.loads(raw);graph=workflows(data,title)
  if graph:return graph
  items=data.items() if isinstance(data,dict) else enumerate(data) if isinstance(data,list) else [('value',data)]
  return [Chunk('json',title,f'{key}: {part}',{'key':str(key)}) for key,value in items for part in slices(dump(value))]
 if ext=='.py':
  try:
   tree=ast.parse(raw);lines=raw.splitlines();records=[];covered=set()
   for node in tree.body:
    if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
     start=min([node.lineno]+[d.lineno for d in node.decorator_list]);end=node.end_lineno;covered.update(range(start,end+1))
     for part in slices('\n'.join(lines[start-1:end])):records.append(Chunk('symbol',title+' · '+node.name,part,{'symbol':node.name,'start':start,'end':end}))
   rest='\n'.join(line for i,line in enumerate(lines,1) if i not in covered);records.extend(Chunk('module',title,part) for part in slices(rest));return records
  except SyntaxError:pass
 return [Chunk('text',title,part) for part in slices(raw)]
