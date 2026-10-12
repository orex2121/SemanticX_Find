import json,os,sys,tempfile
from pathlib import Path
ROOT=Path(os.environ.get('SEMANTICX_HOME',Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1])).resolve()
def bootstrap():
 for name in ('config','models','cache','logs','temp','indexes'):(ROOT/name).mkdir(parents=True,exist_ok=True)
 with tempfile.TemporaryFile(dir=ROOT/'temp'):pass
 for key,value in {'HF_HOME':ROOT/'cache/huggingface','TORCH_HOME':ROOT/'cache/torch','TEMP':ROOT/'temp','TMP':ROOT/'temp','TMPDIR':ROOT/'temp','XDG_CACHE_HOME':ROOT/'cache'}.items():os.environ[key]=str(value)
 os.environ['HF_HUB_DISABLE_TELEMETRY']='1';os.environ['DO_NOT_TRACK']='1';tempfile.tempdir=str(ROOT/'temp')
def atomic_json(path,value):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);fd,tmp=tempfile.mkstemp(dir=path.parent,suffix='.part')
 try:
  with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
  os.replace(tmp,path)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
def read_json(path,default):
 try:return json.loads(Path(path).read_text(encoding='utf-8-sig'))
 except FileNotFoundError:return default
DEFAULTS=dict(language='en',theme='dark',device='auto',dimension=256,batch_size=64,index_workers=4,index_queue_size=32,performance_preset='basic',provider='gemma',vision=True,ocr=True,result_count=50,search_history=[],favorites=[],selected_catalogs=None,selected_file_types=None,result_view='list',keep_model_loaded=True,auto_update=False,auto_update_seconds=60)
def settings():return DEFAULTS|read_json(ROOT/'config/settings.json',{})
