"""Reconstructed persistent retrieval core. See RECOVERY_STATUS.md before reuse."""
import fnmatch,hashlib,json,os,sqlite3,stat,threading,time,uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass,asdict,field
from pathlib import Path
from typing import Protocol
import numpy as np
from filelock import FileLock
from .paths import ROOT,atomic_json,read_json
from .extractors import extract,Chunk,VERSION,normalized,tokens
from .embeddings import LexicalProvider
SCHEMA=1
DEFAULT_EXTENSIONS=['.json','.png','.jpg','.jpeg','.webp','.txt','.md','.html','.htm','.pdf','.py']
def ranking_weights(ranking,semantic_enabled=False):
 weights={'semantic':.45,'lexical':.18,'entities':.24,'structure':.12,'filename':.04,'visual':.45,'ocr':.24}
 # With real embeddings, lexical/structure matches are supporting evidence.
 # Keeping them small prevents generic terms in long notes from overriding
 # a better semantic match, while filename matches still resolve direct lookup.
 if semantic_enabled and ranking in ('hybrid','hybrid_no_structure'):
  weights={'semantic':.78,'lexical':.02,'entities':.12,'structure':.01,'filename':.07,'visual':.78,'ocr':.12}
 if ranking=='semantic':return {'semantic':1}
 if ranking=='lexical':return {'lexical':1}
 if ranking=='filename':return {'filename':1}
 if ranking=='hybrid_no_structure':weights.pop('structure')
 return weights
def score_signals(signal,ranking='hybrid',semantic_enabled=False):
 return sum(signal.get(k,0)*v for k,v in ranking_weights(ranking,semantic_enabled).items())
@dataclass
class Catalog:
 root:str
 id:str=field(default_factory=lambda:uuid.uuid4().hex)
 extensions:list=field(default_factory=lambda:list(DEFAULT_EXTENSIONS))
 include:list=field(default_factory=list)
 exclude:list=field(default_factory=lambda:['*.backup.json','*_temp*','node_modules/*','.git/*'])
 recursive:bool=True
 hidden:bool=False
 max_mb:int=32
 storage:str='auto'
 visual:bool=False
 index_path:str=''
def catalogs():return [Catalog(**x) for x in read_json(ROOT/'config/catalogs.json',[])]
def save_catalogs(values):atomic_json(ROOT/'config/catalogs.json',[asdict(c) for c in values])
class IncompatibleIndex(RuntimeError):pass
class Cancelled(RuntimeError):pass
def register(root,**kwargs):
 root=Path(root).resolve(strict=True)
 if not root.is_dir():raise ValueError('Choose a directory.')
 cat=Catalog(root=str(root),**kwargs);existing=root/'.semantic_index'
 if existing.is_symlink():raise ValueError('Index directory cannot be a symbolic link.')
 if cat.storage=='central':
  dest=ROOT/'indexes'/cat.id
  for candidate in (ROOT/'indexes').glob('*/index.json'):
   prior=read_json(candidate,{})
   if prior.get('root')==str(root) and prior.get('schema')==SCHEMA:dest=candidate.parent;break
 else:
  try:
   existing.mkdir(exist_ok=True);probe=existing/('probe-'+uuid.uuid4().hex);probe.write_bytes(b'');probe.unlink();dest=existing
  except OSError:
   if cat.storage=='local':raise
   dest=ROOT/'indexes'/cat.id
 meta=read_json(dest/'index.json',{})
 if meta:
  if meta.get('schema')!=SCHEMA:raise IncompatibleIndex('Incompatible schema; use a separate central index.')
  cat.id=meta.get('catalog_id',cat.id)
 cat.index_path=str(dest);return cat
def hidden(path):
 try:return path.name.startswith('.') or bool(getattr(path.stat(),'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_HIDDEN',2))
 except OSError:return True
def link(path):return path.is_symlink() or (hasattr(path,'is_junction') and path.is_junction()) or bool(getattr(path.lstat(),'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',1024))
def match(pattern,relative):
 pattern=pattern.replace('\\','/').casefold();relative=relative.replace('\\','/').casefold()
 return fnmatch.fnmatchcase(relative,pattern) or ('/' not in pattern and fnmatch.fnmatchcase(relative.rsplit('/',1)[-1],pattern))
def scan(cat):
 root=Path(cat.root);extensions={value.casefold() for value in cat.extensions}
 if not root.is_dir():raise FileNotFoundError('Catalog offline: '+cat.root)
 errors=[]
 for directory,dirs,files in os.walk(root,followlinks=False,onerror=errors.append):
  base=Path(directory);dirs[:]=[d for d in dirs if d!='.semantic_index' and not link(base/d) and (cat.hidden or not hidden(base/d)) and not any(match(p,(base/d).relative_to(root).as_posix()+'/') for p in cat.exclude)]
  if not cat.recursive:dirs[:]=[]
  for name in files:
   path=base/name;rel=path.relative_to(root).as_posix()
   if link(path) or (not cat.hidden and hidden(path)):continue
   if path.suffix.casefold() not in extensions:continue
   if cat.include and not any(match(p,rel) for p in cat.include):continue
   if any(match(p,rel) for p in cat.exclude):continue
   yield path,rel
 if errors:raise OSError('Incomplete scan; deletion cleanup skipped: '+str(errors[0]))
class JobControl:
 def __init__(self):self.resume_event=threading.Event();self.resume_event.set();self.cancelled=False
 def pause(self):self.resume_event.clear()
 def resume(self):self.resume_event.set()
 def cancel(self):self.cancelled=True;self.resume_event.set()
 def check(self):
  while not self.resume_event.wait(.1):
   if self.cancelled:raise Cancelled()
  if self.cancelled:raise Cancelled()
class VectorStore(Protocol):
 def search(self,connection,vector,k,channel=None,exclude_channel=None):...
class SQLiteExactVectors:
 def search(self,connection,vector,k=200,channel=None,exclude_channel=None):
  sql='SELECT id,vector FROM chunks WHERE vector IS NOT NULL';args=[]
  if channel:sql+=' AND channel=?';args.append(channel)
  if exclude_channel:sql+=' AND channel<>?';args.append(exclude_channel)
  cursor=connection.execute(sql,args);best=[]
  while rows:=cursor.fetchmany(1024):
   matrix=np.stack([np.frombuffer(r['vector'],dtype='<f4') for r in rows]);values=matrix@vector;best.extend((r['id'],float(v)) for r,v in zip(rows,values));best=sorted(best,key=lambda x:x[1],reverse=True)[:k]
  return best
class Index:
 def __init__(self,cat,provider=None):self.cat=cat;self.provider=provider or LexicalProvider();self.base=Path(cat.index_path);self.vectors=SQLiteExactVectors()
 def state(self):
  if not (self.base/'manifest.sqlite').exists():return dict(status='missing',differences=[])
  actual=read_json(self.base/'index.json',{}).get('identity');expected=self.identity()
  if actual==expected:return dict(status='compatible',differences=[])
  differences=[key for key in expected if not isinstance(actual,dict) or actual.get(key)!=expected.get(key)]
  return dict(status='incompatible',differences=differences)
 def connect(self):
  manifest=read_json(self.base/'index.json',{})
  if manifest and manifest.get('schema')!=SCHEMA:raise IncompatibleIndex('Unsupported index schema.')
  self.base.mkdir(parents=True,exist_ok=True);db=sqlite3.connect(self.base/'manifest.sqlite',timeout=15);db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON');db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA synchronous=NORMAL');db.execute('PRAGMA temp_store=MEMORY');db.execute('PRAGMA cache_size=-65536')
  db.executescript('''CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY,relative_path TEXT UNIQUE,size INTEGER,mtime_ns INTEGER,content_hash TEXT,extractor_version TEXT,status TEXT,last_indexed REAL,error TEXT);
CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY,file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,kind TEXT,title TEXT,text TEXT,locator TEXT,channel TEXT,content_hash TEXT,vector BLOB);
CREATE INDEX IF NOT EXISTS chunks_file ON chunks(file_id);
CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(text,tokenize='unicode61');
CREATE TRIGGER IF NOT EXISTS chunk_delete AFTER DELETE ON chunks BEGIN DELETE FROM search_fts WHERE rowid=old.id; END;''');return db
 def identity(self):return {'schema':SCHEMA,'extractor':VERSION,'provider':self.provider.identity,'visual':self.cat.visual}
 def compatibility(self,db):
  row=db.execute("SELECT value FROM meta WHERE key='identity'").fetchone()
  if row and json.loads(row[0])!=self.identity():raise IncompatibleIndex('Model, dimension, extractor or visual mode changed. Rebuild this index.')
 def run(self,progress=lambda s:None,control=None,rebuild=False,force=False,workers=4,queue_size=64):
  if self.cat.visual and not getattr(self.provider,'vision',False):raise ValueError('Visual indexing requires a vision-enabled embedding provider.')
  control=control or JobControl();workers=max(1,int(workers));queue_size=max(1,int(queue_size));counts=dict(processed=0,skipped=0,errors=0,deleted=0,chunks=0);started=time.monotonic();last_file=''
  if not Path(self.cat.root).is_dir():raise FileNotFoundError('Catalog offline: '+self.cat.root)
  self.base.mkdir(parents=True,exist_ok=True)
  with FileLock(str(self.base/'lock'),timeout=0):
   db=self.connect()
   try:
    if rebuild:
     with db:db.execute('DELETE FROM files');db.execute('DELETE FROM meta')
    self.compatibility(db)
    with db:db.execute("INSERT OR REPLACE INTO meta VALUES('identity',?)",(json.dumps(self.identity()),))
    atomic_json(self.base/'index.json',dict(schema=SCHEMA,catalog_id=self.cat.id,root=self.cat.root,identity=self.identity()));seen=set();old_by_rel={row['relative_path']:dict(row) for row in db.execute('SELECT * FROM files')};tasks=[]
    def prepare(task):
     path,rel,old,st=task
     try:
      control.check()
      if isinstance(st,OSError):raise st
      if st.st_size>self.cat.max_mb*1024*1024:raise ValueError('File exceeds maximum size')
      h=hashlib.sha256()
      with path.open('rb') as stream:
       for block in iter(lambda:stream.read(1024*1024),b''):control.check();h.update(block)
      digest=h.hexdigest()
      if old and old['content_hash']==digest and old['status']=='ready':return dict(kind='touch',path=path,rel=rel,old=old,st=st)
      records=extract(path)
      if self.cat.visual and path.suffix.casefold() in ('.png','.jpg','.jpeg','.webp'):
       from PIL import Image,ImageOps
       with Image.open(path) as image:image=ImageOps.exif_transpose(image).convert('RGB');pixel_hash=hashlib.sha256(str(image.size).encode()+image.tobytes()).hexdigest()
       records.append(Chunk('visual',path.name,'Image visual content',{'pixels':pixel_hash},'visual'))
      return dict(kind='prepared',path=path,rel=rel,old=old,st=st,digest=digest,records=records)
     except Cancelled:raise
     except Exception as error:return dict(kind='error',path=path,rel=rel,old=old,error=str(error))
    def flush(batch,pool):
     nonlocal last_file
     if not batch:return
     results=list(pool.map(prepare,batch));text_docs=[];text_slots=[];image_paths=[];image_slots=[]
     for result in results:
      last_file=result['rel']
      if result['kind']!='prepared':continue
      old=result['old'];cached={row['content_hash']:row['vector'] for row in db.execute('SELECT content_hash,vector FROM chunks WHERE file_id=?',(old['id'],))} if old else {};prepared=[]
      for record in result['records']:
       doc='title: '+record.title+' | text: '+record.text;fingerprint=hashlib.sha256((record.channel+'|'+doc+'|'+json.dumps(record.locator,sort_keys=True)).encode()).hexdigest();vector=cached.get(fingerprint);slot=len(prepared);prepared.append([record,fingerprint,vector])
       if vector is None and record.channel=='visual':image_paths.append(result['path']);image_slots.append((result,prepared,slot))
       elif vector is None and self.provider.identity['dimension']:text_docs.append(doc);text_slots.append((prepared,slot))
      result['prepared']=prepared
     control.check()
     if text_docs:
      vectors=self.provider.encode(text_docs)
      if len(vectors)!=len(text_slots):raise RuntimeError('Embedding provider returned an invalid text batch.')
      for (prepared,slot),vector in zip(text_slots,vectors):prepared[slot][2]=np.asarray(vector,dtype='<f4').tobytes()
     control.check()
     if image_paths:
      def encode_image_batch(paths,slots):
       control.check()
       try:
        vectors=self.provider.encode_images(paths)
        if len(vectors)!=len(slots):raise RuntimeError('Embedding provider returned an invalid image batch.')
        for (_,prepared,slot),vector in zip(slots,vectors):prepared[slot][2]=np.asarray(vector,dtype='<f4').tobytes()
       except Cancelled:raise
       except Exception as error:
        # A single corrupt/unsupported image must not abort a large catalog.
        # Split the batch until the failing file is isolated and record only
        # that file as an error.
        message=str(error).casefold()
        if not any(marker in message for marker in ('decode_','image','webp','jpeg','jpg','png','cannot identify')):raise
        if len(paths)>1:
         middle=len(paths)//2;encode_image_batch(paths[:middle],slots[:middle]);encode_image_batch(paths[middle:],slots[middle:]);return
        result,_,_=slots[0];result['kind']='error';result['error']=str(error)
      encode_image_batch(image_paths,image_slots)
     for result in results:
      if result['kind']!='prepared':continue
      try:
       control.check();after=result['path'].stat();st=result['st']
       if (after.st_size,after.st_mtime_ns)!=(st.st_size,st.st_mtime_ns):raise RuntimeError('File changed during indexing; rescan to retry')
      except Cancelled:raise
      except Exception as error:result['kind']='error';result['error']=str(error)
     processed=errors=chunks=skipped=0;chunk_rows=[];relative_by_id={};now=time.time()
     with db:
      for result in results:
       old=result['old'];kind=result['kind'];rel=result['rel']
       if kind=='touch':
        st=result['st'];db.execute('UPDATE files SET mtime_ns=?,size=? WHERE id=?',(st.st_mtime_ns,st.st_size,old['id']));skipped+=1;continue
       if kind=='error':
        errors+=1
        if old:db.execute('DELETE FROM chunks WHERE file_id=?',(old['id'],));db.execute("UPDATE files SET status='error',error=? WHERE id=?",(result['error'],old['id']))
        else:db.execute("INSERT INTO files(relative_path,status,error) VALUES(?,'error',?)",(rel,result['error']))
        continue
       st=result['st']
       if old:
        fid=old['id'];db.execute('DELETE FROM chunks WHERE file_id=?',(fid,));db.execute('UPDATE files SET size=?,mtime_ns=?,content_hash=?,extractor_version=?,status=?,last_indexed=?,error=NULL WHERE id=?',(st.st_size,st.st_mtime_ns,result['digest'],VERSION,'ready',now,fid))
       else:fid=db.execute('INSERT INTO files(relative_path,size,mtime_ns,content_hash,extractor_version,status,last_indexed) VALUES(?,?,?,?,?,?,?)',(rel,st.st_size,st.st_mtime_ns,result['digest'],VERSION,'ready',now)).lastrowid
       relative_by_id[fid]=rel;processed+=1;chunks+=len(result['prepared'])
       chunk_rows.extend((fid,record.kind,record.title,record.text,json.dumps(record.locator,ensure_ascii=False),record.channel,fingerprint,vector) for record,fingerprint,vector in result['prepared'])
      if chunk_rows:
       db.executemany('INSERT INTO chunks(file_id,kind,title,text,locator,channel,content_hash,vector) VALUES(?,?,?,?,?,?,?,?)',chunk_rows);ids=list(relative_by_id);placeholders=','.join('?' for _ in ids);fts=[(row['id'],normalized(relative_by_id[row['file_id']]+' '+row['text'])) for row in db.execute(f'SELECT id,file_id,text FROM chunks WHERE file_id IN ({placeholders})',ids)];db.executemany('INSERT INTO search_fts(rowid,text) VALUES(?,?)',fts)
     counts['processed']+=processed;counts['errors']+=errors;counts['chunks']+=chunks;counts['skipped']+=skipped;progress(dict(counts,file=last_file,elapsed=round(time.monotonic()-started,2),workers=workers,queue_size=queue_size))
    with ThreadPoolExecutor(max_workers=workers,thread_name_prefix='semanticx-index') as pool:
     for path,rel in scan(self.cat):
      control.check();seen.add(rel);old=old_by_rel.get(rel);last_file=rel
      try:st=path.stat()
      except OSError as error:tasks.append((path,rel,old,error));st=None
      if st is not None and not force and old and old['size']==st.st_size and old['mtime_ns']==st.st_mtime_ns and old['status']=='ready':
       counts['skipped']+=1
       if counts['skipped']%250==0:progress(dict(counts,file=rel,elapsed=round(time.monotonic()-started,2),workers=workers,queue_size=queue_size))
       continue
      if st is not None:tasks.append((path,rel,old,st))
      if len(tasks)>=queue_size:flush(tasks,pool);tasks=[]
     flush(tasks,pool)
    control.check()
    with db:
     for row in db.execute('SELECT id,relative_path FROM files').fetchall():
      if row['relative_path'] not in seen:db.execute('DELETE FROM files WHERE id=?',(row['id'],));counts['deleted']+=1
     db.execute("INSERT OR REPLACE INTO meta VALUES('last_scan',?)",(str(time.time()),))
    progress(dict(counts,file=last_file,elapsed=round(time.monotonic()-started,2),workers=workers,queue_size=queue_size))
    return counts
   finally:db.close()
 def search(self,query,limit=50,image_paths=None,extension='',path_filter='',node='',model='',minimum=0,ocr_text='',ranking='hybrid',modified_after_ns=0,max_size_bytes=0,source='all',extensions=None):
  if ranking not in ('filename','lexical','semantic','hybrid_no_structure','hybrid'):raise ValueError('Unknown ranking mode: '+ranking)
  if source not in ('all','vision','text'):raise ValueError('Unknown search source: '+source)
  if not (self.base/'manifest.sqlite').exists():return []
  db=self.connect()
  try:
   db.execute('BEGIN');self.compatibility(db);signals={};query_tokens=list(dict.fromkeys(tokens(query+' '+ocr_text)))[:48];allowed_extensions=None if extensions is None else {value.casefold() for value in extensions}
   if source!='vision' and query_tokens and ranking in ('filename','hybrid','hybrid_no_structure'):
    # Filename baseline must find substrings even when FTS has no whole-token hit.
    candidates=[]
    for row in db.execute("SELECT f.relative_path,min(c.id) cid FROM files f JOIN chunks c ON c.file_id=f.id WHERE f.status='ready' GROUP BY f.id"):
     value=sum(w in row['relative_path'].casefold() for w in query_tokens)/len(query_tokens)
     if value:candidates.append((value,row['cid']))
    for value,cid in sorted(candidates,reverse=True)[:400]:signals.setdefault(cid,{})['filename']=value
   if source!='vision' and query_tokens and ranking!='filename':
    expression=' OR '.join('"'+w.replace('"','""')+'"' for w in query_tokens)
    for rank,row in enumerate(db.execute('SELECT rowid,bm25(search_fts) rank FROM search_fts WHERE search_fts MATCH ? ORDER BY rank LIMIT 400',(expression,))):signals.setdefault(row['rowid'],{})['lexical']=1/(1+rank/12)
   if query and self.provider.identity['dimension'] and ranking not in ('filename','lexical'):
    channel='visual' if source=='vision' else None;exclude='visual' if source=='text' else None;signal_name='visual' if source=='vision' else 'semantic'
    for cid,value in self.vectors.search(db,self.provider.encode([query],query=True)[0],channel=channel,exclude_channel=exclude):signals.setdefault(cid,{})[signal_name]=max(0,value)
   if source!='text' and image_paths and not getattr(self.provider,'vision',False) and not ocr_text:raise RuntimeError('Image search requires vision or local OCR.')
   for image in (image_paths or []) if source!='text' and getattr(self.provider,'vision',False) and ranking in ('hybrid','hybrid_no_structure') else []:
    for cid,value in self.vectors.search(db,self.provider.encode_images([image])[0],channel='visual'):
     d=signals.setdefault(cid,{});d['visual']=max(d.get('visual',0),max(0,value))
   ranked={}
   for cid,signal in signals.items():
    row=db.execute('SELECT c.*,f.relative_path,f.size,f.mtime_ns FROM chunks c JOIN files f ON c.file_id=f.id WHERE c.id=? AND f.status=?',(cid,'ready')).fetchone()
    if not row:continue
    rel=row['relative_path']
    if allowed_extensions is not None and Path(rel).suffix.casefold() not in allowed_extensions:continue
    if allowed_extensions is None and extension and Path(rel).suffix.casefold()!=extension.casefold():continue
    if path_filter and path_filter.casefold() not in rel.casefold():continue
    if modified_after_ns and (row['mtime_ns'] or 0)<modified_after_ns:continue
    if max_size_bytes and (row['size'] or 0)>max_size_bytes:continue
    if node and not db.execute("SELECT 1 FROM chunks WHERE file_id=? AND kind='node' AND lower(text) LIKE ? ESCAPE '\\'",(row['file_id'],'%'+node.casefold().replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%')).fetchone():continue
    if model and not db.execute("SELECT 1 FROM chunks WHERE file_id=? AND kind='overview' AND lower(locator) LIKE ? ESCAPE '\\'",(row['file_id'],'%'+model.casefold().replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%')).fetchone():continue
    text=normalized(row['text']);loc=json.loads(row['locator']);operations=loc.get('operations',[]);exact=[] if source=='vision' else [w for w in query_tokens if w in text.split()];structural=[] if source=='vision' else [w for w in query_tokens if any(w in op.split() for op in operations)]
    if source!='vision':signal['entities']=len(exact)/max(1,len(query_tokens));signal['structure']=len(structural)/max(1,len(query_tokens));signal['filename']=sum(w in rel.casefold() for w in query_tokens)/max(1,len(query_tokens));signal['ocr']=sum(w in text.split() for w in tokens(ocr_text))/max(1,len(tokens(ocr_text)))
    weights=ranking_weights(ranking,bool(self.provider.identity['dimension']))
    score=score_signals(signal,ranking,bool(self.provider.identity['dimension']));evidence=dict(channel=row['channel'],text=row['text'],locator=loc,kind=row['kind'],signals=dict(signal));current=ranked.get(row['file_id'])
    if current is None:
     current=dict(path=str(Path(self.cat.root)/rel),relative_path=rel,catalog_id=self.cat.id,size=row['size'] or 0,mtime_ns=row['mtime_ns'] or 0,score=score,signals=dict(signal),matched_terms=exact,channel=row['channel'],text=row['text'],locator=loc,kind=row['kind'],evidence=[evidence],best_chunk_score=score);ranked[row['file_id']]=current
    else:
     for key,value in signal.items():current['signals'][key]=max(current['signals'].get(key,0),value)
     current['matched_terms']=sorted(set(current['matched_terms'])|set(exact))
     if row['channel'] not in [x['channel'] for x in current['evidence']]:current['evidence'].append(evidence)
     if score>current['best_chunk_score']:current.update(channel=row['channel'],text=row['text'],locator=loc,kind=row['kind'],best_chunk_score=score)
    current['score']=sum(current['signals'].get(k,0)*v for k,v in weights.items())
   return sorted((r for r in ranked.values() if r['score']>=minimum and r['score']>0),key=lambda r:r['score'],reverse=True)[:limit]
  finally:db.close()
 def files(self,limit=None,relative_paths=None):
  if not (self.base/'manifest.sqlite').exists():return []
  db=self.connect()
  try:
   args=list(relative_paths or []);where=(' WHERE f.relative_path IN ('+','.join('?' for _ in args)+')') if args else ' WHERE 0' if relative_paths is not None else '';sql='SELECT f.*,count(c.id) chunks FROM files f LEFT JOIN chunks c ON c.file_id=f.id'+where+' GROUP BY f.id ORDER BY relative_path'+(' LIMIT '+str(int(limit)) if limit else '');return [dict(r) for r in db.execute(sql,args)]
  finally:db.close()
 def file_stats(self,relative_paths=None):
  if not (self.base/'manifest.sqlite').exists():return dict(files=0,ready=0,errors=0,chunks=0,last_indexed=0)
  db=self.connect()
  try:
   args=list(relative_paths or []);where=(' WHERE f.relative_path IN ('+','.join('?' for _ in args)+')') if args else ' WHERE 0' if relative_paths is not None else ''
   row=db.execute("SELECT count(*) files,coalesce(sum(f.status='ready'),0) ready,coalesce(sum(f.status='error'),0) errors,coalesce(sum(coalesce(c.chunks,0)),0) chunks,coalesce(max(f.last_indexed),0) last_indexed FROM files f LEFT JOIN (SELECT file_id,count(*) chunks FROM chunks GROUP BY file_id)c ON c.file_id=f.id"+where,args).fetchone()
   return dict(row)
  finally:db.close()
 def duplicates(self):
  if not (self.base/'manifest.sqlite').exists():return []
  db=self.connect()
  try:
   sql="""SELECT f.*,count(c.id) chunks,d.copies FROM files f JOIN (SELECT content_hash,count(*) copies FROM files WHERE status='ready' AND content_hash IS NOT NULL GROUP BY content_hash HAVING count(*)>1) d ON d.content_hash=f.content_hash LEFT JOIN chunks c ON c.file_id=f.id GROUP BY f.id ORDER BY f.content_hash,f.relative_path"""
   return [dict(r) for r in db.execute(sql)]
  finally:db.close()
