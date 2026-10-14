"""Desktop search and catalog management. Background results apply after thread exit."""
import csv,json,os,platform,shutil,subprocess,sys,time,uuid
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import Qt,QEvent,QRect,QThread,Signal,QUrl,QByteArray,QMimeData,QTimer,QSize,qVersion
from PySide6.QtGui import QDesktopServices,QIcon,QKeySequence,QShortcut,QPixmap,QDrag,QImageReader,QPainter,QColor
from PySide6.QtWidgets import QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QLabel,QPushButton,QLineEdit,QComboBox,QTabWidget,QSplitter,QListWidget,QListWidgetItem,QTextBrowser,QFileDialog,QDialog,QFormLayout,QDialogButtonBox,QSpinBox,QDoubleSpinBox,QCheckBox,QMessageBox,QScrollArea,QFrame,QMenu,QAbstractItemView,QStyledItemDelegate,QStyleOptionViewItem,QListView,QSizePolicy
from filelock import FileLock,Timeout
from .paths import ROOT,settings,read_json,atomic_json
from .engine import Index,catalogs,save_catalogs,register,JobControl,Cancelled,DEFAULT_EXTENSIONS
from .embeddings import GemmaProvider,LexicalProvider,ModelManager
from .capture import Capture
from . import __version__
class ClickableImage(QLabel):
 clicked=Signal(str)
 def __init__(self,path='',parent=None):super().__init__(parent);self.path=path
 def mousePressEvent(self,event):
  if event.button()==Qt.LeftButton:self.clicked.emit(self.path)
  super().mousePressEvent(event)
class FileDragList(QListWidget):
 resized=Signal()
 def __init__(self,parent=None):
  super().__init__(parent);self.setDragEnabled(True);self.setDragDropMode(QAbstractItemView.DragOnly);self.setDefaultDropAction(Qt.CopyAction);self.setSelectionMode(QAbstractItemView.ExtendedSelection)
 def resizeEvent(self,event):super().resizeEvent(event);self.resized.emit()
 def wheelEvent(self,event):
  if self.viewMode()==QListView.IconMode:
   delta=event.pixelDelta().y()
   if not delta:delta=(event.angleDelta().y()/120)*max(120,self.gridSize().height())*2
   bar=self.verticalScrollBar();bar.setValue(bar.value()-int(delta));event.accept();return
  super().wheelEvent(event)
 def drag_mime(self):
  paths=[];items=self.selectedItems() or ([self.currentItem()] if self.currentItem() else [])
  for item in items:
   value=item.data(Qt.UserRole)
   if value and Path(value).is_file():
    path=str(Path(value).resolve())
    if path not in paths:paths.append(path)
  if not paths:return None
  mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(path) for path in paths]);mime.setText('\n'.join(paths));return mime
 def startDrag(self,supported_actions):
  mime=self.drag_mime()
  if not mime:return
  drag=QDrag(self);drag.setMimeData(mime)
  item=self.currentItem()
  if item and not item.icon().isNull():drag.setPixmap(item.icon().pixmap(72,72))
  drag.exec(Qt.CopyAction,Qt.CopyAction)
VISION_ROLE=Qt.UserRole+1
def catalog_vision_indexed(catalog):
 base=Path(catalog.index_path);identity=read_json(base/'index.json',{}).get('identity',{});return (base/'manifest.sqlite').is_file() and bool(identity.get('visual'))
def vision_icon(size=20):
 pixmap=QPixmap(size,size);pixmap.fill(Qt.transparent);painter=QPainter(pixmap);painter.setRenderHint(QPainter.Antialiasing);painter.setBrush(QColor('#20a866'));painter.setPen(Qt.NoPen);painter.drawEllipse(1,1,size-2,size-2);font=painter.font();font.setBold(True);font.setPixelSize(max(10,size-8));painter.setFont(font);painter.setPen(QColor('white'));painter.drawText(pixmap.rect(),Qt.AlignCenter,'V');painter.end();return QIcon(pixmap)
class CatalogItemDelegate(QStyledItemDelegate):
 def paint(self,painter,option,index):
  visual=bool(index.data(VISION_ROLE));base=QStyleOptionViewItem(option)
  if visual:base.rect=option.rect.adjusted(0,0,-28,0)
  super().paint(painter,base,index)
  if visual:
   badge=QRect(option.rect.right()-23,option.rect.center().y()-9,18,18);painter.save();painter.setRenderHint(QPainter.Antialiasing);painter.setBrush(QColor('#20a866'));painter.setPen(Qt.NoPen);painter.drawEllipse(badge);font=painter.font();font.setBold(True);font.setPixelSize(11);painter.setFont(font);painter.setPen(QColor('white'));painter.drawText(badge,Qt.AlignCenter,'V');painter.restore()
class CatalogCheckCombo(QComboBox):
 selectionChanged=Signal()
 def __init__(self,parent=None):
  super().__init__(parent);self.all_text='';self.count_text='{count}';self.none_text='';self.keep_popup=False;self.setEditable(True);self.lineEdit().setReadOnly(True);self.lineEdit().installEventFilter(self);self.view().setItemDelegate(CatalogItemDelegate(self.view()));self.view().pressed.connect(self._pressed)
 def eventFilter(self,watched,event):
  if watched is self.lineEdit() and event.type()==QEvent.MouseButtonPress and event.button()==Qt.LeftButton:self.showPopup();return True
  return super().eventFilter(watched,event)
 def set_catalogs(self,catalogs,all_text,count_text,none_text,selected=None):
  self.clear();self.all_text=all_text;self.count_text=count_text;self.none_text=none_text;wanted=set(selected) if selected is not None else {c.id for c in catalogs};self.addItem(all_text,None)
  for c in catalogs:self.addItem(Path(c.root).name,c.id);self.setItemData(self.count()-1,catalog_vision_indexed(c),VISION_ROLE)
  for row in range(self.count()):self.model().item(row).setFlags(self.model().item(row).flags()|Qt.ItemIsUserCheckable)
  for row in range(1,self.count()):self.setItemData(row,Qt.Checked if self.itemData(row) in wanted else Qt.Unchecked,Qt.CheckStateRole)
  self._sync_all();self._update_summary()
 def set_selected_ids(self,values):
  if values is None:values=[self.itemData(row) for row in range(1,self.count())]
  wanted=set(values)
  for row in range(1,self.count()):self.setItemData(row,Qt.Checked if self.itemData(row) in wanted else Qt.Unchecked,Qt.CheckStateRole)
  self._sync_all();self._update_summary()
 def selected_ids(self):return [self.itemData(row) for row in range(1,self.count()) if self.itemData(row,Qt.CheckStateRole)==Qt.Checked]
 def _pressed(self,index):
  self.keep_popup=True;QTimer.singleShot(150,lambda:setattr(self,'keep_popup',False));row=index.row();checked=(all(self.itemData(i,Qt.CheckStateRole)==Qt.Checked for i in range(1,self.count())) if row==0 else self.itemData(row,Qt.CheckStateRole)==Qt.Checked);QTimer.singleShot(0,lambda:self._apply_toggle(row,Qt.Unchecked if checked else Qt.Checked))
 def hidePopup(self):
  if self.keep_popup:self.keep_popup=False;return
  super().hidePopup()
 def _apply_toggle(self,row,state):
  if row==0:
   for i in range(1,self.count()):self.setItemData(i,state,Qt.CheckStateRole)
  else:self.setItemData(row,state,Qt.CheckStateRole)
  self._sync_all();self._update_summary();self.selectionChanged.emit()
 def _sync_all(self):
  states=[self.itemData(row,Qt.CheckStateRole)==Qt.Checked for row in range(1,self.count())];self.setItemData(0,Qt.Checked if all(states) else Qt.PartiallyChecked if any(states) else Qt.Unchecked,Qt.CheckStateRole)
 def _update_summary(self):
  rows=[row for row in range(1,self.count()) if self.itemData(row,Qt.CheckStateRole)==Qt.Checked];text=self.all_text if len(rows)==max(0,self.count()-1) else self.none_text if not rows else self.itemText(rows[0]) if len(rows)==1 else self.count_text.format(count=len(rows));self.lineEdit().setText(text);self.setToolTip('\n'.join(self.itemText(row) for row in rows) or self.none_text)
class FileTypeCheckCombo(CatalogCheckCombo):
 def set_extensions(self,extensions,all_text,count_text,none_text,selected=None):
  self.clear();self.all_text=all_text;self.count_text=count_text;self.none_text=none_text;wanted=set(selected) if selected is not None else set(extensions);self.addItem(all_text,None)
  for extension in extensions:self.addItem(extension,extension)
  for row in range(self.count()):self.model().item(row).setFlags(self.model().item(row).flags()|Qt.ItemIsUserCheckable)
  for row in range(1,self.count()):self.setItemData(row,Qt.Checked if self.itemData(row) in wanted else Qt.Unchecked,Qt.CheckStateRole)
  self._sync_all();self._update_summary()
 def selected_extensions(self):return self.selected_ids()
class Worker(QThread):
 progress=Signal(object);completed=Signal(object);failed=Signal(str)
 def __init__(self,fn,parent=None):super().__init__(parent);self.fn=fn;self.result=None;self.error=None
 def run(self):
  try:self.result=self.fn(self.progress.emit)
  except Cancelled:self.result={'cancelled':True}
  except Exception as e:self.error=f'{type(e).__name__}: {e}'
def open_path(path,select=False):
 path=Path(path).resolve()
 if select and sys.platform=='win32':subprocess.Popen(['explorer.exe','/select,',str(path)])
 else:QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent if select else path)))
IMAGE_EXTENSIONS=('.png','.jpg','.jpeg','.webp')
SEARCH_MODES=(('search_mode_vision_only','vision_only'),('search_mode_text_only','text_only'),('search_mode_vision_first','vision_first'),('search_mode_text_first','text_first'))
PERFORMANCE_PRESETS={'minimum':(2,32,16),'basic':(4,64,32),'balanced':(8,128,64),'high':(16,256,128),'maximum':(32,512,256)}
def search_source_order(mode):
 return {'vision_only':('vision',),'text_only':('text',),'vision_first':('vision','text'),'text_first':('text','vision')}.get(mode,('vision','text'))
def scaled_image(path,size):
 reader=QImageReader(str(path));reader.setAutoTransform(True);original=reader.size()
 if original.isValid():reader.setScaledSize(original.scaled(size,Qt.KeepAspectRatio))
 image=reader.read();return QPixmap.fromImage(image) if not image.isNull() else QPixmap()
class Window(QMainWindow):
 def __init__(self):
  super().__init__();self.prepare_session_temp();self.cfg=settings();self.data=catalogs();self.results=[];self.images=[];self.temp_images=[];self.jobs=[];self.control=None;self.provider=None;self.image_preview=None;self.preview_pixmap=None;self.activity_buttons={};self.activity_timer=QTimer(self);self.activity_timer.setInterval(280);self.activity_timer.timeout.connect(self.advance_button_activity);self.auto_timer=QTimer(self);self.auto_timer.timeout.connect(self.auto_update_catalogs);self.setWindowTitle('SemanticX Find');self.setWindowIcon(QIcon(str(ROOT/'assets/semanticx.ico')));self.resize(1260,840);self.setAcceptDrops(True);self.capture=Capture(self);self.capture.done.connect(self.attach_pixmap);self.build();self.restore_window_geometry();QShortcut(QKeySequence('Ctrl+K'),self,activated=lambda:self.query.setFocus());QShortcut(QKeySequence('Ctrl+Shift+S'),self,activated=self.start_capture);QShortcut(QKeySequence('Ctrl+V'),self,activated=self.paste)
 def cleanup_stale_temp_sessions(self):
  root=(ROOT/'temp').resolve();root.mkdir(parents=True,exist_ok=True)
  for directory in root.glob('session-*'):
   if not directory.is_dir() or directory.resolve().parent!=root:continue
   lock=FileLock(str(directory/'active.lock'))
   try:lock.acquire(timeout=0)
   except Timeout:continue
   else:
    lock.release()
    try:shutil.rmtree(directory)
    except OSError:pass
  cutoff=time.time()-86400
  for path in root.glob('query-*.png'):
   try:
    if path.is_file() and path.stat().st_mtime<cutoff:path.unlink()
   except OSError:pass
 def prepare_session_temp(self):
  self.cleanup_stale_temp_sessions();self.session_temp=ROOT/'temp'/('session-'+uuid.uuid4().hex);self.session_temp.mkdir(parents=True,exist_ok=False);self.session_lock=FileLock(str(self.session_temp/'active.lock'));self.session_lock.acquire(timeout=0)
 def shutdown_session_temp(self):
  if getattr(self,'session_lock',None) and self.session_lock.is_locked:self.session_lock.release()
  directory=getattr(self,'session_temp',None)
  if directory and directory.exists() and directory.resolve().parent==(ROOT/'temp').resolve():
   try:shutil.rmtree(directory)
   except OSError:pass
 def t(self,key):return read_json(ROOT/f'locales/{self.cfg["language"]}.json',{}).get(key,key)
 def button(self,key,fn):
  b=QPushButton(self.t(key));b.clicked.connect(fn);return b
 def catalog_button(self,key,fn):
  button=self.button(key,fn);button.setToolTip(self.t('catalog_tip_'+key));return button
 def option_label(self,title,help_text=None):
  suffix=f' <span style="font-size:10px;color:#8fa3b8">— {self.t(help_text)}</span>' if help_text else ''
  label=QLabel(f'<b>{self.t(title)}</b>{suffix}');label.setWordWrap(False)
  if help_text:label.setToolTip(self.t(title)+' — '+self.t(help_text))
  return label
 def settings_row(self,form,key,widget,help_key):
  help_text=self.t(help_key);label=QLabel(self.t(key));label.setToolTip(help_text);widget.setToolTip(help_text);form.addRow(label,widget);return label
 def vision_state(self):
  if self.cfg.get('provider')!='gemma' or not self.cfg.get('vision',False):return 'disabled'
  return 'ready' if ModelManager().status()['ready'] else 'unavailable'
 def refresh_vision_badge(self):
  if getattr(self,'vision_badge',None) is None:return
  state=self.vision_state();colors={'ready':('#173f2c','#70e3a2'),'disabled':('#293442','#b5c4d3'),'unavailable':('#4b2525','#ff9b9b')};background,foreground=colors[state];self.vision_badge.setText(self.t('vision_'+state));self.vision_badge.setStyleSheet(f'background:{background};color:{foreground};border:1px solid {foreground};border-radius:6px;padding:8px;font-weight:600');visual_catalogs=sum(c.visual for c in self.data);self.vision_badge.setToolTip(self.t('vision_catalogs')+': '+str(visual_catalogs))
 def update_vision_controls(self):
  enabled=self.engine.currentText()=='gemma';help_text=self.t('vision_help') if enabled else self.t('vision_requires_gemma');self.vision.setEnabled(enabled);self.vision_help.setText(help_text);self.vision.setToolTip(help_text)
 def build(self):
  state=self.view_state() if hasattr(self,'query') else {}
  self.vision_badge=None
  self.menuBar().clear();self.menuBar().hide();central=QWidget();layout=QVBoxLayout(central);header=QHBoxLayout();logo=QLabel();logo.setPixmap(QPixmap(str(ROOT/'assets/logo.svg')).scaled(48,48));header.addWidget(logo);title=QLabel('SemanticX Find');title.setStyleSheet('font-size:26px;font-weight:700');header.addWidget(title);header.addStretch();layout.addLayout(header);self.tabs=QTabWidget();layout.addWidget(self.tabs)
  search=QWidget();box=QVBoxLayout(search);controls=QGridLayout();controls.setHorizontalSpacing(8);controls.setVerticalSpacing(5);self.query=QLineEdit();self.query.setObjectName('primaryQuery');self.query.setStyleSheet('QLineEdit{background:#173a59;color:#f5fbff;border:2px solid #39a6ff;border-radius:6px;padding:8px} QLineEdit:focus{border-color:#7cc7ff}');self.query.setPlaceholderText(self.t('placeholder'));self.query.returnPressed.connect(self.search);self.search_mode=QComboBox()
  for key,value in SEARCH_MODES:self.search_mode.addItem(self.t(key),value)
  self.search_mode.setCurrentIndex(self.search_mode.findData('vision_first'));self.history=QComboBox();self.history.currentIndexChanged.connect(self.select_search_history);self.populate_search_history();self.scope=CatalogCheckCombo();self.scope.setObjectName('primaryCatalog');self.scope.setStyleSheet('QComboBox{background:#173a59;color:#f5fbff;border:2px solid #39a6ff;border-radius:6px;padding:8px}');self.scope.set_catalogs(self.data,self.t('all_catalogs'),self.t('catalogs_selected'),self.t('no_catalogs_selected'));self.scope.selectionChanged.connect(self.save_catalog_selection);self.search_button=self.button('search',self.search);self.search_button.setObjectName('primarySearch');self.search_button.setStyleSheet('QPushButton{background:#147ac1;color:white;border:2px solid #57b8ff;border-radius:6px;padding:9px;font-weight:700} QPushButton:hover{background:#2094df} QPushButton:pressed{background:#07598d;border-color:#d5efff;padding-top:11px;padding-bottom:7px} QPushButton[busy="true"]{background:#a45b08;border-color:#ffd37d}');self.capture_button=self.button('capture',self.start_capture);self.capture_button.setObjectName('primaryCapture');self.capture_button.setStyleSheet('QPushButton{background:#196448;color:white;border:2px solid #55d39a;border-radius:6px;padding:9px;font-weight:700} QPushButton:hover{background:#23805d} QPushButton:pressed{background:#0d4933;border-color:#c5ffe2;padding-top:11px;padding-bottom:7px}');controls.addWidget(self.option_label('catalog_scope_title','catalog_scope_help'),0,0);controls.addWidget(self.option_label('search_mode_title','search_mode_help'),0,1);controls.addWidget(self.option_label('search_history_title','search_history_help'),0,2);controls.addWidget(self.scope,1,0);controls.addWidget(self.search_mode,1,1);controls.addWidget(self.history,1,2);controls.addWidget(self.option_label('query_title','query_help'),2,0,1,3);controls.addWidget(self.query,3,0,1,3);controls.addWidget(self.search_button,3,3);controls.addWidget(self.option_label('image_search_title','image_search_help'),4,0,1,4);self.attach_button=self.button('attach',self.attach);controls.addWidget(self.attach_button,5,0,1,2);controls.addWidget(self.capture_button,5,2,1,2);controls.setColumnStretch(0,2);controls.setColumnStretch(1,2);controls.setColumnStretch(2,2);box.addLayout(controls);filters=QGridLayout();filters.setHorizontalSpacing(8)
  available=list(dict.fromkeys(DEFAULT_EXTENSIONS+[x.casefold() for c in self.data for x in c.extensions]))
  self.extension=FileTypeCheckCombo();self.extension.set_extensions(available,self.t('all_types'),self.t('types_selected'),self.t('no_types_selected'));self.extension.selectionChanged.connect(self.save_file_type_selection)
  self.modified=QComboBox()
  for key,days in [('all_time',0),('today',1),('last_7_days',7),('last_30_days',30),('last_year',365)]:self.modified.addItem(self.t(key),days)
  self.max_size=QDoubleSpinBox();self.max_size.setRange(0,1048576);self.max_size.setDecimals(0);self.max_size.setSpecialValueText(self.t('any_size'));self.max_size.setSuffix(' '+self.t('mb'));self.minimum=QSpinBox();self.minimum.setRange(0,100);self.minimum.setSingleStep(1);self.minimum.setValue(35);self.minimum.setSuffix(' %');filters.addWidget(self.option_label('file_type_title','file_type_help'),0,0);filters.addWidget(self.option_label('modified_title','modified_help'),0,1);filters.addWidget(self.option_label('size_title','size_help'),0,2);filters.addWidget(self.option_label('minimum_title','minimum_help'),0,3);filters.addWidget(self.extension,1,0);filters.addWidget(self.modified,1,1);filters.addWidget(self.max_size,1,2);filters.addWidget(self.minimum,1,3);box.addLayout(filters);self.attachment_scroll=QScrollArea();self.attachment_scroll.setObjectName('attachmentScroll');self.attachment_scroll.setWidgetResizable(True);self.attachment_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded);self.attachment_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff);self.attachment_scroll.setFixedHeight(126);self.attachment_host=QWidget();self.attachment_layout=QHBoxLayout(self.attachment_host);self.attachment_layout.setContentsMargins(6,6,6,6);self.attachment_layout.setSpacing(8);self.attachment_layout.setAlignment(Qt.AlignLeft);self.attachment_scroll.setWidget(self.attachment_host);box.addWidget(self.attachment_scroll);split=QSplitter();results_panel=QWidget();results_layout=QVBoxLayout(results_panel);results_layout.setContentsMargins(0,0,0,0);self.list=FileDragList();self.list.setToolTip(self.t('drag_files_hint'));self.list.currentRowChanged.connect(self.show_result);self.list.itemDoubleClicked.connect(lambda item:self.result_action('open'));self.list.setContextMenuPolicy(Qt.CustomContextMenu);self.list.customContextMenuRequested.connect(self.show_result_menu);self.list.resized.connect(self.position_view_button);results_layout.addWidget(self.list,1);self.view_button=QPushButton('▦ '+self.t('view'),self.list);self.view_button.setObjectName('viewButton');self.view_button.setStyleSheet('QPushButton{background-color:rgba(32,52,73,205);color:white;border:1px solid rgba(130,170,205,220);border-radius:6px;padding:7px 10px} QPushButton:hover{background-color:rgba(42,72,99,240);border-color:#8fc6ef} QPushButton::menu-indicator{background:transparent}');self.view_menu=QMenu(self.view_button);self.result_view_actions={}
  for key,mode in [('view_large','large'),('view_normal','normal'),('view_small','small'),('view_list','list')]:
   action=self.view_menu.addAction(self.t(key));action.setCheckable(True);action.triggered.connect(lambda checked=False,m=mode:self.set_result_view(m));self.result_view_actions[mode]=action
  self.view_button.setMenu(self.view_menu);self.view_button.adjustSize();self.view_button.raise_();split.addWidget(results_panel);details_panel=QWidget();details_layout=QVBoxLayout(details_panel);details_layout.setContentsMargins(0,0,0,0);self.result_preview=ClickableImage();self.result_preview.setObjectName('resultPreview');self.result_preview.setAlignment(Qt.AlignCenter);self.result_preview.setMinimumHeight(190);self.result_preview.setMaximumHeight(300);self.result_preview.setCursor(Qt.PointingHandCursor);self.result_preview.clicked.connect(self.toggle_image_preview);self.result_preview.hide();self.result_preview_source=None;details_layout.addWidget(self.result_preview);self.details=QTextBrowser();details_layout.addWidget(self.details,1);split.addWidget(details_panel);self.set_result_view(self.cfg.get('result_view','list'),False);QTimer.singleShot(0,self.position_view_button);box.addWidget(split,1);row=QHBoxLayout()
  for key,action in [('open_file','open'),('open_folder','folder'),('copy_path','copy'),('show_catalog','catalog')]:row.addWidget(self.button(key,lambda checked=False,a=action:self.result_action(a)))
  row.addWidget(self.button('toggle_favorite',self.toggle_favorite));row.addWidget(self.button('export_results',self.export_results))
  box.addLayout(row);self.tabs.addTab(search,self.t('search'))
  page=QWidget();box=QVBoxLayout(page);row=QHBoxLayout()
  self.catalog_buttons={}
  for key,fn in [('add',self.add_catalog),('catalog_settings',self.edit_catalog),('update',lambda:self.index_catalog(False)),('rebuild',lambda:self.index_catalog(True)),('remove',self.remove_catalog),('pause',self.pause),('cancel',self.cancel)]:self.catalog_buttons[key]=self.catalog_button(key,fn);row.addWidget(self.catalog_buttons[key])
  box.addLayout(row);self.catalog_list=QListWidget();self.catalog_list.setIconSize(QSize(20,20))
  for c in self.data:
   item=QListWidgetItem(c.root)
   if catalog_vision_indexed(c):item.setIcon(vision_icon())
   self.catalog_list.addItem(item)
  self.catalog_list.currentRowChanged.connect(self.catalog_selected);self.catalog_splitter=QSplitter(Qt.Horizontal);catalog_panel=QWidget();catalog_panel_layout=QVBoxLayout(catalog_panel);catalog_panel_layout.setContentsMargins(0,0,0,0);catalog_panel_layout.addWidget(self.option_label('catalogs_panel_title'),0);catalog_panel_layout.addWidget(self.catalog_list,1);self.catalog_splitter.addWidget(catalog_panel);self.catalog_content_splitter=QSplitter(Qt.Horizontal);details_panel=QWidget();details_panel_layout=QVBoxLayout(details_panel);details_panel_layout.setContentsMargins(0,0,0,0);details_panel_layout.addWidget(self.option_label('catalog_info_title'),0);self.catalog_details=QTextBrowser();details_panel_layout.addWidget(self.catalog_details,1);self.catalog_content_splitter.addWidget(details_panel);files_panel=QWidget();files_panel_layout=QVBoxLayout(files_panel);files_panel_layout.setContentsMargins(0,0,0,0);files_panel_layout.addWidget(self.option_label('indexed_files_title'),0);self.catalog_file_list=FileDragList();self.catalog_file_list.setToolTip(self.t('drag_files_hint'));self.catalog_file_list.itemDoubleClicked.connect(lambda item:self.catalog_file_action('open'));self.catalog_file_list.setContextMenuPolicy(Qt.CustomContextMenu);self.catalog_file_list.customContextMenuRequested.connect(self.show_catalog_file_menu);files_panel_layout.addWidget(self.catalog_file_list,1);self.catalog_content_splitter.addWidget(files_panel);self.catalog_content_splitter.setStretchFactor(0,1);self.catalog_content_splitter.setStretchFactor(1,1);self.catalog_content_splitter.setSizes([360,420]);self.catalog_splitter.addWidget(self.catalog_content_splitter);self.catalog_splitter.setStretchFactor(0,1);self.catalog_splitter.setStretchFactor(1,2);self.catalog_splitter.setSizes([360,900]);box.addWidget(self.catalog_splitter,1);row=QHBoxLayout()
  for key,action in [('open_file','open'),('open_folder','folder'),('copy_path','copy')]:self.catalog_buttons[key]=self.catalog_button(key,lambda checked=False,a=action:self.catalog_file_action(a));row.addWidget(self.catalog_buttons[key])
  box.addLayout(row);self.tabs.addTab(page,self.t('catalogs'))
  page=QWidget();box=QVBoxLayout(page);model_row=QHBoxLayout();self.model_status=QTextBrowser();self.model_status.setMaximumHeight(210);model_row.addWidget(self.model_status,1);self.model_download_button=self.button('download',lambda:self.model_job(False));self.model_verify_button=self.button('verify',lambda:self.model_job(True));model_row.addWidget(self.model_download_button,0,Qt.AlignTop);model_row.addWidget(self.model_verify_button,0,Qt.AlignTop);box.addLayout(model_row);ocr_row=QHBoxLayout();self.ocr_status=QTextBrowser();self.ocr_status.setMaximumHeight(190);ocr_row.addWidget(self.ocr_status,1);self.ocr_download_button=self.button('download',lambda:self.ocr_job(False));self.ocr_verify_button=self.button('verify',lambda:self.ocr_job(True));ocr_row.addWidget(self.ocr_download_button,0,Qt.AlignTop);ocr_row.addWidget(self.ocr_verify_button,0,Qt.AlignTop);box.addLayout(ocr_row);box.addStretch();self.tabs.addTab(page,self.t('models'));self.refresh_model_status()
  page=QWidget();form=QFormLayout(page);self.settings_form=form;self.language=QComboBox();self._applying_preset=False
  for name,code in [('English','en'),('Русский','ru'),('Français','fr'),('Español','es')]:self.language.addItem(name,code)
  self.language.setCurrentIndex(self.language.findData(self.cfg['language']));self.settings_row(form,'language',self.language,'language_help');self.language.currentIndexChanged.connect(self.change_language);self.theme=QComboBox()
  for key in ('system','light','dark'):self.theme.addItem(self.t('theme_'+key),key)
  self.theme.setCurrentIndex(self.theme.findData(self.cfg['theme']));self.settings_row(form,'theme',self.theme,'theme_help')
  self.performance_preset=QComboBox();self.performance_preset.addItem(self.t('preset_custom'),'custom')
  for key in PERFORMANCE_PRESETS:
   self.performance_preset.addItem(self.t('preset_'+key),key);self.performance_preset.setItemData(self.performance_preset.count()-1,self.t('preset_'+key+'_help'),Qt.ToolTipRole)
  self.settings_row(form,'performance_preset',self.performance_preset,'performance_preset_help')
  self.index_workers=QComboBox()
  for value in (2,4,8,16,32):self.index_workers.addItem(str(value),value)
  self.index_workers.setCurrentIndex(max(0,self.index_workers.findData(int(self.cfg.get('index_workers',8)))));self.settings_row(form,'index_workers',self.index_workers,'index_workers_help')
  self.batch=QComboBox()
  for value in (32,64,128,256,512):self.batch.addItem(str(value),value)
  self.batch.setCurrentIndex(max(0,self.batch.findData(int(self.cfg.get('batch_size',128)))));self.settings_row(form,'batch',self.batch,'batch_help')
  self.index_queue_size=QComboBox()
  for value in (16,32,64,128,256,512):self.index_queue_size.addItem(str(value),value)
  self.index_queue_size.setCurrentIndex(max(0,self.index_queue_size.findData(int(self.cfg.get('index_queue_size',64)))));self.settings_row(form,'index_queue_size',self.index_queue_size,'index_queue_size_help');self.sync_performance_preset();self.performance_preset.currentIndexChanged.connect(self.apply_performance_preset);self.index_workers.currentIndexChanged.connect(self.sync_performance_preset);self.batch.currentIndexChanged.connect(self.sync_performance_preset);self.index_queue_size.currentIndexChanged.connect(self.sync_performance_preset)
  self.result_count=QSpinBox();self.result_count.setRange(1,1000);self.result_count.setValue(self.cfg['result_count']);self.settings_row(form,'result_count',self.result_count,'result_count_help');self.engine=QComboBox();self.engine.addItems(['lexical','gemma']);self.engine.setCurrentText(self.cfg['provider']);self.settings_row(form,'provider',self.engine,'provider_help');self.device=QComboBox();self.device.addItems(['auto','cpu','cuda']);self.device.setCurrentText(self.cfg['device']);self.settings_row(form,'device',self.device,'device_help');self.dimension=QComboBox();self.dimension.addItems(['128','256','512','768']);self.dimension.setCurrentText(str(self.cfg['dimension']));self.settings_row(form,'dimension',self.dimension,'dimension_help');self.vision=QCheckBox(self.t('vision_enabled'));self.vision.setChecked(self.cfg.get('vision',False));self.vision.setToolTip(self.t('vision_help'));self.vision_help=QLabel(self.t('vision_help'));self.vision_help.setWordWrap(False);self.vision_help.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred);self.vision_help.setToolTip(self.t('vision_help'));form.addRow(self.vision,self.vision_help);self.engine.currentTextChanged.connect(self.update_vision_controls);self.update_vision_controls();self.ocr=QCheckBox('OCR');self.ocr.setChecked(self.cfg.get('ocr',False));self.ocr.setToolTip(self.t('ocr_help'));self.ocr_help=QLabel(self.t('ocr_help'));self.ocr_help.setWordWrap(False);self.ocr_help.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred);self.ocr_help.setToolTip(self.t('ocr_help'));form.addRow(self.ocr,self.ocr_help);self.keep_model_loaded=QCheckBox(self.t('keep_model_loaded'));self.keep_model_loaded.setChecked(self.cfg.get('keep_model_loaded',True));self.keep_model_loaded.setToolTip(self.t('keep_model_loaded_help'));self.keep_model_help=QLabel(self.t('keep_model_loaded_help'));self.keep_model_help.setWordWrap(False);self.keep_model_help.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred);self.keep_model_help.setToolTip(self.t('keep_model_loaded_help'));form.addRow(self.keep_model_loaded,self.keep_model_help);self.auto_update=QCheckBox(self.t('auto_update'));self.auto_update.setChecked(self.cfg.get('auto_update',False));self.auto_update.setToolTip(self.t('auto_update_help'));form.addRow(self.auto_update);self.auto_update_seconds=QSpinBox();self.auto_update_seconds.setRange(15,3600);self.auto_update_seconds.setSuffix(' '+self.t('seconds'));self.auto_update_seconds.setValue(self.cfg.get('auto_update_seconds',60));self.settings_row(form,'auto_update_interval',self.auto_update_seconds,'auto_update_interval_help');form.addRow(self.button('save',self.save_settings));self.tabs.addTab(page,self.t('settings'))
  page=QWidget();box=QVBoxLayout(page);self.favorites_list=FileDragList();self.favorites_list.setToolTip(self.t('drag_files_hint'));self.favorites_list.itemDoubleClicked.connect(lambda item:self.favorite_action('open'));self.favorites_list.setContextMenuPolicy(Qt.CustomContextMenu);self.favorites_list.customContextMenuRequested.connect(self.show_favorite_menu);box.addWidget(self.favorites_list);row=QHBoxLayout()
  for key,action in [('open_file','open'),('open_folder','folder'),('copy_path','copy'),('remove_favorite','remove')]:row.addWidget(self.button(key,lambda checked=False,a=action:self.favorite_action(a)))
  box.addLayout(row);self.tabs.addTab(page,self.t('favorites'));self.refresh_favorites();footer=QHBoxLayout();self.status=QLabel(self.t('ready'));self.status.setWordWrap(True);footer.addWidget(self.status,1);self.version_label=QLabel(__version__);footer.addWidget(self.version_label);self.help_button=QPushButton(self.t('information'));help_menu=QMenu(self.help_button);help_menu.addAction(self.t('about'),self.about);help_menu.addAction(self.t('guide'),lambda:open_path(ROOT/'README_RU.md'));self.help_button.setMenu(help_menu);footer.addWidget(self.help_button);layout.addLayout(footer);self.setCentralWidget(central)
  QApplication.instance().styleHints().setColorScheme({'system':Qt.ColorScheme.Unknown,'light':Qt.ColorScheme.Light,'dark':Qt.ColorScheme.Dark}[self.cfg['theme']])
  self.setStyleSheet('')
  button_feedback='QPushButton:pressed{background:#0f78aa;border-color:#a9e3ff;padding-top:11px;padding-bottom:7px} QPushButton[busy="true"]{background:#a45b08;border:2px solid #ffd37d;font-weight:700}'
  self.setStyleSheet(button_feedback)
  if self.cfg['theme']=='dark':self.setStyleSheet('QMainWindow,QDialog,QWidget{background:#101a27;color:#e7f2ff;font-family:Segoe UI;font-size:13px} QLineEdit,QTextBrowser,QListWidget,QComboBox{background:#192a3d;border:1px solid #35506a;border-radius:6px;padding:8px} QPushButton{background:#203449;border:1px solid #42627c;border-radius:6px;padding:9px} QPushButton:pressed{background:#0f78aa;border-color:#a9e3ff;padding-top:11px;padding-bottom:7px} QPushButton[busy="true"]{background:#a45b08;border:2px solid #ffd37d;font-weight:700} QPushButton#viewButton{background:#203449;border:1px solid #6b8ba6;padding:7px 10px} QTabBar::tab{padding:12px} QFrame#attachmentCard{background:#192a3d;border:1px solid #35506a;border-radius:6px} QLabel#attachmentThumbnail{background:#0c1520;border-radius:4px} QPushButton#attachmentRemove{background:#d93232;color:white;border:1px solid #ff7777;border-radius:9px;padding:0;font-weight:700} QLabel#imagePreview{background:#080c12} QLabel#resultPreview{background:#0c1520;border:1px solid #35506a;border-radius:6px}')
  self.restore_view(state);self.configure_auto_update()
 def view_state(self):
  return dict(query=self.query.text(),search_mode=self.search_mode.currentData(),scopes=self.scope.selected_ids(),scope_available=[self.scope.itemData(row) for row in range(1,self.scope.count())],extensions=self.extension.selected_extensions(),extensions_available=[self.extension.itemData(row) for row in range(1,self.extension.count())],tab=self.tabs.currentIndex(),catalog=self.current_catalog().id if self.current_catalog() else None,minimum=self.minimum.value(),modified=self.modified.currentData(),max_size=self.max_size.value())
 def restore_view(self,state):
  if 'scopes' in state:
   selected=state.get('scopes');previous=state.get('scope_available');selected=None if previous is not None and set(selected or [])==set(previous) else selected
  else:selected=self.cfg.get('selected_catalogs')
  if 'extensions' in state:
   selected_extensions=state.get('extensions');previous_extensions=state.get('extensions_available');selected_extensions=None if previous_extensions is not None and set(selected_extensions or [])==set(previous_extensions) else selected_extensions
  else:selected_extensions=self.cfg.get('selected_file_types')
  self.query.setText(state.get('query',''));self.search_mode.setCurrentIndex(max(0,self.search_mode.findData(state.get('search_mode','vision_first'))));self.scope.set_selected_ids(selected);self.tabs.setCurrentIndex(state.get('tab',0));self.extension.set_selected_ids(selected_extensions);self.minimum.setValue(state.get('minimum',35));self.modified.setCurrentIndex(max(0,self.modified.findData(state.get('modified',0))));self.max_size.setValue(state.get('max_size',0));self.refresh_attachments()
  self.save_catalog_selection();self.save_file_type_selection()
  self.refresh_result_items()
  for i,c in enumerate(self.data):
   if c.id==state.get('catalog'):self.catalog_list.setCurrentRow(i);break
 def save_catalog_selection(self):
  if not hasattr(self,'scope'):return
  self.cfg['selected_catalogs']=self.scope.selected_ids();atomic_json(ROOT/'config/settings.json',self.cfg)
 def save_file_type_selection(self):
  if not hasattr(self,'extension'):return
  self.cfg['selected_file_types']=self.extension.selected_extensions();atomic_json(ROOT/'config/settings.json',self.cfg)
 def busy(self):return bool(self.jobs)
 def repolish(self,widget):
  widget.style().unpolish(widget);widget.style().polish(widget);widget.update()
 def start_button_activity(self,button):
  if button is None:return
  self.activity_buttons[button]=[button.text(),0];button.setProperty('busy',True);button.setEnabled(False);self.advance_button_activity()
  if not self.activity_timer.isActive():self.activity_timer.start()
 def advance_button_activity(self):
  frames=('● ○ ○','○ ● ○','○ ○ ●')
  for button,state in list(self.activity_buttons.items()):
   try:state[1]=(state[1]+1)%len(frames);button.setText(f'{state[0]}  {frames[state[1]]}');self.repolish(button)
   except RuntimeError:self.activity_buttons.pop(button,None)
  if not self.activity_buttons:self.activity_timer.stop()
 def stop_button_activity(self,button):
  state=self.activity_buttons.pop(button,None)
  if state:
   try:button.setText(state[0]);button.setProperty('busy',False);button.setEnabled(True);self.repolish(button)
   except RuntimeError:pass
  if not self.activity_buttons:self.activity_timer.stop()
 def launch(self,fn,done=None,busy_button=None):
  if self.busy():self.status.setText(self.t('busy'));return
  job=Worker(fn,self);job.busy_button=busy_button;self.jobs.append(job);self.start_button_activity(busy_button);job.progress.connect(lambda value:self.status.setText(str(value)));job.finished.connect(lambda:self.job_finished(job,done));job.start()
 def job_finished(self,job,done):
  self.jobs.remove(job);self.control=None;self.stop_button_activity(getattr(job,'busy_button',None))
  try:
   if job.error:self.status.setText(job.error)
   elif isinstance(job.result,dict) and job.result.get('cancelled'):self.status.setText(self.t('cancelled'))
   else:
    self.status.setText(self.t('done')+((' '+str(job.result)) if job.result is not None else ''))
    if done:done(job.result)
  except Exception as e:self.status.setText(f'{type(e).__name__}: {e}')
  finally:
   if not self.cfg.get('keep_model_loaded',True):self.release_provider()
   job.deleteLater()
 def get_provider(self):
  if self.provider is None:self.provider=GemmaProvider(self.cfg['dimension'],self.cfg['device'],self.cfg['batch_size'],self.cfg.get('vision',False)) if self.cfg['provider']=='gemma' else LexicalProvider()
  return self.provider
 def release_provider(self):
  provider=self.provider;self.provider=None
  if provider is not None and hasattr(provider,'unload'):provider.unload()
 def search(self):
  text=self.query.text();self.record_search(text);selected=set(self.scope.selected_ids());cats=[c for c in self.data if c.id in selected];images=list(self.images);mode=self.search_mode.currentData();days=self.modified.currentData() or 0;selected_extensions=self.extension.selected_extensions();extensions=None if len(selected_extensions)==max(0,self.extension.count()-1) else selected_extensions;filters=dict(extensions=extensions,minimum=self.minimum.value()/100,modified_after_ns=time.time_ns()-int(days*86400*1e9) if days else 0,max_size_bytes=int(self.max_size.value()*1048576) if self.max_size.value() else 0,limit=self.cfg['result_count']);count=self.cfg['result_count']
  def work(progress):
   provider=self.get_provider();ocr_text=''
   if images and self.cfg.get('ocr'):
    from .ocr import RapidImageQueryAnalyzer
    analyzer=RapidImageQueryAnalyzer();ocr_text=' '.join(analyzer.analyze(p) for p in images)
   for source in search_source_order(mode):
    result=[]
    for c in cats:result.extend(Index(c,provider).search(text,image_paths=images,ocr_text=ocr_text,source=source,**filters))
    result=sorted(result,key=lambda r:r['score'],reverse=True)[:count]
    if result:return result
   return []
  self.launch(work,self.search_done,self.search_button)
 def populate_search_history(self):
  self.history.blockSignals(True);self.history.clear();self.history.addItem(self.t('search_history'),None)
  for value in self.cfg.get('search_history',[]):self.history.addItem(value,value)
  if self.cfg.get('search_history'):self.history.insertSeparator(self.history.count());self.history.addItem(self.t('clear_history'),'__clear__')
  self.history.setCurrentIndex(0);self.history.blockSignals(False)
 def record_search(self,text):
  text=text.strip()
  if not text:return
  values=[text]+[value for value in self.cfg.get('search_history',[]) if value.casefold()!=text.casefold()];self.cfg['search_history']=values[:20];atomic_json(ROOT/'config/settings.json',self.cfg);self.populate_search_history()
 def select_search_history(self,index):
  value=self.history.itemData(index)
  if value=='__clear__':self.cfg['search_history']=[];atomic_json(ROOT/'config/settings.json',self.cfg);self.populate_search_history()
  elif value:self.query.setText(value);self.query.setFocus()
 def search_done(self,result):
  self.results=result;preferred=self.cfg.get('result_view','list');has_images=any(Path(row['path']).suffix.casefold() in IMAGE_EXTENSIONS for row in result);target='list' if result and not has_images else preferred
  if self.result_view_mode!=target:self.set_result_view(target,False)
  else:self.refresh_result_items()
  self.status.setText(self.t('result_count')+': '+str(len(result)))
 def export_rows(self):
  signal_keys=('filename','lexical','semantic','entities','structure','visual','ocr');rows=[]
  for rank,result in enumerate(self.results,1):
   row=dict(rank=rank,filename=Path(result['path']).name,full_path=result['path'],relative_path=result['relative_path'],catalog_id=result['catalog_id'],score=result['score'],size_bytes=result.get('size',0),modified=datetime.fromtimestamp(result.get('mtime_ns',0)/1e9).isoformat(sep=' ',timespec='seconds') if result.get('mtime_ns') else '')
   row.update({'signal_'+key:result.get('signals',{}).get(key,0) for key in signal_keys});rows.append(row)
  return rows
 def export_results(self,path=''):
  if not self.results:self.status.setText(self.t('no_results'));return
  if not isinstance(path,(str,Path)) or not str(path):
   suggested='semanticx-results-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.csv';path,_=QFileDialog.getSaveFileName(self,self.t('export_results'),suggested,'CSV (*.csv);;JSON (*.json)')
  if not path:return
  path=Path(path);temporary=path.with_name(path.name+'.part');rows=self.export_rows()
  try:
   if path.suffix.casefold()=='.json':temporary.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
   else:
    with temporary.open('w',encoding='utf-8-sig',newline='') as output:
     writer=csv.DictWriter(output,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
   os.replace(temporary,path);self.status.setText(self.t('export_done')+': '+str(path))
  except Exception as e:
   temporary.unlink(missing_ok=True);self.status.setText(self.t('export_error')+': '+str(e))
 def favorite_key(self,path):return str(Path(path).resolve()).casefold()
 def is_favorite(self,path):return self.favorite_key(path) in {self.favorite_key(x) for x in self.cfg.get('favorites',[])}
 def refresh_result_items(self):
  if not hasattr(self,'list'):return
  current=self.list.currentRow();tiles=getattr(self,'result_view_mode','list')!='list';self.list.clear()
  for result in self.results:
   favorite='★ ' if self.is_favorite(result['path']) else '';name=favorite+Path(result['path']).name
   if tiles:text=name
   else:
    score=float(result.get('score',0));percent=max(0,min(100,score*100));text=f'{self.t("result_score")}: {score:.3f} ({percent:.1f}%)\n{name}\n{self.t("file_size")}: {self.format_bytes(result.get("size",0))}'
   self.list.addItem(text)
  for i,result in enumerate(self.results):
   item=self.list.item(i);item.setData(Qt.UserRole,result['path']);item.setToolTip(result['path']);path=Path(result['path'])
   if path.suffix.casefold() in IMAGE_EXTENSIONS and path.is_file():
    pixmap=scaled_image(path,self.list.iconSize())
    if not pixmap.isNull():item.setIcon(QIcon(pixmap))
   if not tiles:item.setSizeHint(QSize(0,96))
  self.list.setCurrentRow(min(max(current,0),len(self.results)-1) if self.results else -1)
 def set_result_view(self,mode,persist=True):
  if mode not in ('large','normal','small','list'):mode='list'
  self.result_view_mode=mode
  for key,action in getattr(self,'result_view_actions',{}).items():action.setChecked(key==mode)
  if mode=='list':
   self.list.setViewMode(QListView.ListMode);self.list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel);self.list.verticalScrollBar().setSingleStep(72);self.list.setFlow(QListView.TopToBottom);self.list.setWrapping(False);self.list.setWordWrap(False);self.list.setUniformItemSizes(False);self.list.setIconSize(QSize(72,72));self.list.setGridSize(QSize());self.list.setSpacing(3)
  else:
   size={'small':96,'normal':150,'large':220}[mode];self.list.setViewMode(QListView.IconMode);self.list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel);self.list.verticalScrollBar().setSingleStep(max(96,size));self.list.setFlow(QListView.LeftToRight);self.list.setWrapping(True);self.list.setWordWrap(True);self.list.setUniformItemSizes(True);self.list.setResizeMode(QListView.Adjust);self.list.setMovement(QListView.Static);self.list.setIconSize(QSize(size,size));self.list.setGridSize(QSize(size+42,size+68));self.list.setSpacing(6)
  if persist:self.cfg['result_view']=mode;atomic_json(ROOT/'config/settings.json',self.cfg)
  self.refresh_result_items();self.position_view_button()
 def position_view_button(self):
  if not hasattr(self,'view_button') or not hasattr(self,'list'):return
  self.view_button.adjustSize();scroll_width=self.list.verticalScrollBar().width() if self.list.verticalScrollBar().isVisible() else 0;self.view_button.move(max(8,self.list.width()-self.view_button.width()-scroll_width-10),8);self.view_button.raise_()
 def toggle_favorite(self):
  i=self.list.currentRow()
  if not 0<=i<len(self.results):return
  path=self.results[i]['path'];values=list(self.cfg.get('favorites',[]));key=self.favorite_key(path);existing=next((x for x in values if self.favorite_key(x)==key),None)
  if existing is None:values.append(str(Path(path).resolve()));message='favorite_added'
  else:values.remove(existing);message='favorite_removed'
  self.cfg['favorites']=values;atomic_json(ROOT/'config/settings.json',self.cfg);self.refresh_result_items();self.refresh_favorites();self.status.setText(self.t(message))
 def refresh_favorites(self):
  if not hasattr(self,'favorites_list'):return
  self.favorites_list.clear()
  for value in self.cfg.get('favorites',[]):
   path=Path(value);self.favorites_list.addItem(('★ ' if path.exists() else '⚠ ')+path.name+'\n'+str(path));self.favorites_list.item(self.favorites_list.count()-1).setData(Qt.UserRole,str(path))
  if self.favorites_list.count():self.favorites_list.setCurrentRow(0)
 def favorite_action(self,action):
  item=self.favorites_list.currentItem()
  if not item:return
  path=Path(item.data(Qt.UserRole))
  if action=='open':open_path(path)
  elif action=='folder':open_path(path,True)
  elif action=='copy':QApplication.clipboard().setText(str(path))
  elif action=='copy_name':QApplication.clipboard().setText(path.name)
  elif action=='copy_folder':QApplication.clipboard().setText(str(path.parent))
  elif action=='catalog':
   match=next(((i,c) for i,c in enumerate(self.data) if path.is_relative_to(Path(c.root))),None)
   if match:
    i,c=match;self.tabs.setCurrentIndex(1);self.catalog_list.setCurrentRow(i);self.show_catalog_files(c,[path.relative_to(c.root).as_posix()])
   else:self.status.setText(self.t('favorite_not_catalog'))
  elif action=='remove':
   self.cfg['favorites']=[x for x in self.cfg.get('favorites',[]) if self.favorite_key(x)!=self.favorite_key(path)];atomic_json(ROOT/'config/settings.json',self.cfg);self.refresh_favorites();self.refresh_result_items();self.status.setText(self.t('favorite_removed'))
 def show_favorite_menu(self,pos):
  if not self.favorites_list.currentItem():return
  menu=QMenu(self)
  for key,action in [('open_file','open'),('open_folder','folder'),('copy_path','copy'),('copy_name','copy_name'),('copy_folder','copy_folder'),('show_catalog','catalog')]:menu.addAction(self.t(key),lambda checked=False,a=action:self.favorite_action(a))
  menu.addSeparator();menu.addAction(self.t('remove_favorite'),lambda:self.favorite_action('remove'));menu.exec(self.favorites_list.viewport().mapToGlobal(pos))
 def show_result(self,row):
  self.details.clear();self.set_result_preview(None)
  if 0<=row<len(self.results):
   r=self.results[row];self.set_result_preview(r['path']);metadata=f'{self.t("file_size")}: {self.format_bytes(r.get("size",0))}\n{self.t("file_modified")}: {datetime.fromtimestamp(r.get("mtime_ns",0)/1e9).strftime("%Y-%m-%d %H:%M:%S") if r.get("mtime_ns") else "—"}';self.details.setPlainText(r['path']+'\n'+metadata+'\n\n'+self.t('why')+'\n'+'\n'.join(self.t('signal_'+key)+f': {value:.3f}' for key,value in r['signals'].items() if value>0)+'\n\n'+r['text'])
 def set_result_preview(self,path):
  if not hasattr(self,'result_preview'):return
  if not path or Path(path).suffix.casefold() not in IMAGE_EXTENSIONS or not Path(path).is_file():
   self.result_preview.hide();self.result_preview.clear();self.result_preview.path='';self.result_preview_source=None;return
  self.result_preview_source=scaled_image(path,QSize(1200,800));self.result_preview.path=str(path);self.result_preview.setToolTip(self.t('click_to_expand'));self.update_result_preview();self.result_preview.setVisible(not self.result_preview_source.isNull())
 def update_result_preview(self):
  source=getattr(self,'result_preview_source',None)
  if source and not source.isNull():self.result_preview.setPixmap(source.scaled(max(200,self.result_preview.width()),max(180,self.result_preview.height()),Qt.KeepAspectRatio,Qt.SmoothTransformation))
 def result_action(self,action):
  i=self.list.currentRow()
  if not 0<=i<len(self.results):return
  r=self.results[i]
  if action=='open':open_path(r['path'])
  elif action=='folder':open_path(r['path'],True)
  elif action=='copy':QApplication.clipboard().setText(r['path'])
  elif action=='copy_name':QApplication.clipboard().setText(Path(r['path']).name)
  elif action=='copy_folder':QApplication.clipboard().setText(str(Path(r['path']).parent))
  else:
   self.tabs.setCurrentIndex(1)
   for i,c in enumerate(self.data):
    if c.id==r['catalog_id']:self.catalog_list.setCurrentRow(i);break
   self.show_catalog_files(self.current_catalog(),[x['relative_path'] for x in self.results if x['catalog_id']==r['catalog_id']])
 def show_result_menu(self,pos):
  if not 0<=self.list.currentRow()<len(self.results):return
  menu=QMenu(self)
  for key,action in [('open_file','open'),('open_folder','folder'),('copy_path','copy'),('copy_name','copy_name'),('copy_folder','copy_folder'),('show_catalog','catalog')]:menu.addAction(self.t(key),lambda checked=False,a=action:self.result_action(a))
  menu.addSeparator();menu.addAction(self.t('toggle_favorite'),self.toggle_favorite)
  menu.exec(self.list.viewport().mapToGlobal(pos))
 def add_catalog(self,path=''):
  if self.busy():return
  if not isinstance(path,str) or not path:path=QFileDialog.getExistingDirectory(self,self.t('add'))
  if not path:return
  if any(Path(c.root)==Path(path).resolve() for c in self.data):self.status.setText(self.t('duplicate_catalog'));return
  dlg=QDialog(self);form=QFormLayout(dlg);ext=QLineEdit(', '.join(DEFAULT_EXTENSIONS));include=QLineEdit();exclude=QLineEdit('*.backup.json, *_temp*, node_modules/*, .git/*');visual=QCheckBox(self.t('visual'));form.addRow(self.t('extensions'),ext);form.addRow(self.t('include'),include);form.addRow(self.t('exclude'),exclude);form.addRow(visual);recursive=QCheckBox(self.t('recursive'));recursive.setChecked(True);hidden=QCheckBox(self.t('hidden'));max_mb=QSpinBox();max_mb.setRange(1,4096);max_mb.setValue(32);storage=QComboBox()
  for key in ('auto','local','central'):storage.addItem(self.t('storage_'+key),key)
  form.addRow(recursive);form.addRow(hidden);form.addRow(self.t('max_mb'),max_mb);form.addRow(self.t('storage'),storage);buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);buttons.accepted.connect(dlg.accept);buttons.rejected.connect(dlg.reject);form.addRow(buttons)
  if dlg.exec():
   try:
    c=register(path,extensions=['.'+x.strip().lstrip('.').lower() for x in ext.text().split(',') if x.strip()],include=[x.strip() for x in include.text().split(',') if x.strip()],exclude=[x.strip() for x in exclude.text().split(',') if x.strip()],visual=visual.isChecked(),recursive=recursive.isChecked(),hidden=hidden.isChecked(),max_mb=max_mb.value(),storage=storage.currentData());self.data.append(c);save_catalogs(self.data);self.build()
   except Exception as e:self.status.setText(str(e))
 def edit_catalog(self):
  if self.busy():return
  c=self.current_catalog()
  if not c:return
  dlg=QDialog(self);dlg.setWindowTitle(self.t('catalog_settings'));form=QFormLayout(dlg);ext=QLineEdit(', '.join(c.extensions));include=QLineEdit(', '.join(c.include));exclude=QLineEdit(', '.join(c.exclude));visual=QCheckBox(self.t('visual'));visual.setChecked(c.visual);recursive=QCheckBox(self.t('recursive'));recursive.setChecked(c.recursive);hidden=QCheckBox(self.t('hidden'));hidden.setChecked(c.hidden);max_mb=QSpinBox();max_mb.setRange(1,4096);max_mb.setValue(c.max_mb);form.addRow(self.t('extensions'),ext);form.addRow(self.t('include'),include);form.addRow(self.t('exclude'),exclude);form.addRow(visual);form.addRow(recursive);form.addRow(hidden);form.addRow(self.t('max_mb'),max_mb)
  if self.vision_state()!='ready':warning=QLabel(self.t('vision_catalog_warning'));warning.setWordWrap(True);warning.setStyleSheet('color:#e6a34a');form.addRow(warning)
  buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);buttons.accepted.connect(dlg.accept);buttons.rejected.connect(dlg.reject);form.addRow(buttons)
  if dlg.exec():self.apply_catalog_settings(c,dict(extensions=['.'+x.strip().lstrip('.').lower() for x in ext.text().split(',') if x.strip()],include=[x.strip() for x in include.text().split(',') if x.strip()],exclude=[x.strip() for x in exclude.text().split(',') if x.strip()],visual=visual.isChecked(),recursive=recursive.isChecked(),hidden=hidden.isChecked(),max_mb=max_mb.value()))
 def apply_catalog_settings(self,c,values):
  visual_changed=c.visual!=values['visual']
  for key,value in values.items():setattr(c,key,value)
  save_catalogs(self.data);self.build();self.status.setText(self.t('catalog_saved_rebuild') if visual_changed else self.t('catalog_saved'))
 def current_catalog(self):
  i=self.catalog_list.currentRow();return self.data[i] if 0<=i<len(self.data) else None
 def catalog_selected(self,*args):
  c=self.current_catalog()
  if c:
   try:self.show_catalog_files(c)
   except Exception as e:self.catalog_details.setPlainText(str(e))
  else:self.catalog_details.clear();self.catalog_file_list.clear()
 def show_catalog_files(self,c,relative_paths=None):
  index=Index(c,self.get_provider());files=index.files(limit=2000,relative_paths=relative_paths);stats=index.file_stats(relative_paths=relative_paths);state=index.state();online=Path(c.root).is_dir();state_text=self.t('index_'+state['status'])
  if state['differences']:state_text+=' ('+', '.join(state['differences'])+')'
  lines=[f'{self.t("catalog_path")}: {c.root}',f'{self.t("catalog_status")}: {self.t("online") if online else self.t("offline")}',f'{self.t("catalog_index_state")}: {state_text}',f'{self.t("catalog_files")}: {stats["files"]}',f'{self.t("catalog_ready")}: {stats["ready"]}',f'{self.t("catalog_chunks")}: {stats["chunks"]}',f'{self.t("catalog_errors")}: {stats["errors"]}',f'{self.t("catalog_last_indexed")}: {datetime.fromtimestamp(stats["last_indexed"]).strftime("%Y-%m-%d %H:%M:%S") if stats["last_indexed"] else self.t("never")}',f'{self.t("extensions")}: {", ".join(c.extensions)}',f'{self.t("catalog_index_path")}: {c.index_path}',f'{self.t("visual")}: {self.t("yes") if c.visual else self.t("no")}']
  self.catalog_details.setPlainText('\n'.join(lines));self.catalog_details.verticalScrollBar().setValue(0);self.catalog_file_list.clear()
  for item in files:
   marker='✓' if item['status']=='ready' else '⚠';line=f'{marker} {item["relative_path"]}  ·  {self.t("catalog_chunks")}: {item["chunks"]}'
   if item.get('error'):line+=f'  ·  {item["error"]}'
   self.catalog_file_list.addItem(line);self.catalog_file_list.item(self.catalog_file_list.count()-1).setData(Qt.UserRole,str(Path(c.root)/item['relative_path']))
  if not files:self.catalog_file_list.addItem(self.t('catalog_empty'))
  elif self.catalog_file_list.count():self.catalog_file_list.setCurrentRow(0)
 def show_duplicates(self):
  c=self.current_catalog()
  if not c:return
  try:files=Index(c).duplicates()
  except Exception as e:self.catalog_details.setPlainText(str(e));return
  groups={value:i+1 for i,value in enumerate(dict.fromkeys(x['content_hash'] for x in files))};self.catalog_details.setPlainText('\n'.join([f'{self.t("catalog_path")}: {c.root}',f'{self.t("duplicate_groups")}: {len(groups)}',f'{self.t("duplicate_files")}: {len(files)}']));self.catalog_file_list.clear()
  for item in files:
   line=f'⧉ {self.t("duplicate_group")} {groups[item["content_hash"]]}  ·  {item["relative_path"]}  ·  {self.format_bytes(item["size"] or 0)}';self.catalog_file_list.addItem(line);self.catalog_file_list.item(self.catalog_file_list.count()-1).setData(Qt.UserRole,str(Path(c.root)/item['relative_path']))
  if files:self.catalog_file_list.setCurrentRow(0)
  else:self.catalog_file_list.addItem(self.t('no_duplicates'))
 def catalog_file_action(self,action):
  c=self.current_catalog();item=self.catalog_file_list.currentItem()
  if not c or not item:return
  value=item.data(Qt.UserRole)
  if not value:return
  stored=Path(value);path=stored if stored.is_absolute() else Path(c.root)/stored
  if action=='open':open_path(path)
  elif action=='folder':open_path(path,True)
  elif action=='copy':QApplication.clipboard().setText(str(path))
  elif action=='copy_name':QApplication.clipboard().setText(path.name)
  elif action=='copy_folder':QApplication.clipboard().setText(str(path.parent))
 def show_catalog_file_menu(self,pos):
  if not self.catalog_file_list.currentItem() or not self.catalog_file_list.currentItem().data(Qt.UserRole):return
  menu=QMenu(self)
  for key,action in [('open_file','open'),('open_folder','folder'),('copy_path','copy'),('copy_name','copy_name'),('copy_folder','copy_folder')]:menu.addAction(self.t(key),lambda checked=False,a=action:self.catalog_file_action(a))
  menu.exec(self.catalog_file_list.viewport().mapToGlobal(pos))
 def index_catalog(self,rebuild=False):
  if self.busy():self.status.setText(self.t('busy'));return
  c=self.current_catalog()
  if not c:return
  busy_button=self.catalog_buttons['rebuild' if rebuild else 'update'];index=Index(c,self.get_provider())
  if rebuild and QMessageBox.question(self,self.t('rebuild'),self.t('rebuild_confirm'))!=QMessageBox.Yes:return
  if not rebuild and index.state()['status']=='incompatible':
   if QMessageBox.question(self,self.t('rebuild'),self.t('rebuild_required_confirm'))!=QMessageBox.Yes:return
   rebuild=True
  self.control=JobControl();self.launch(lambda progress:index.run(progress,self.control,rebuild=rebuild,workers=self.cfg.get('index_workers',8),queue_size=self.cfg.get('index_queue_size',64)),lambda _:self.catalog_selected(),busy_button)
 def remove_catalog(self):
  if self.busy():return
  c=self.current_catalog()
  if c:self.data.remove(c);save_catalogs(self.data);self.build()
 def pause(self):
  if self.control:
   if self.control.resume_event.is_set():self.control.pause()
   else:self.control.resume()
 def cancel(self):
  if self.control:self.control.cancel()
 def model_job(self,verify=False):
  if self.busy():self.status.setText(self.t('busy'));return
  self.control=JobControl();self.launch(lambda p:ModelManager().verify(p,self.control) if verify else ModelManager().download(p,self.control),lambda _:self.refresh_model_status())
 def ocr_download(self):
  self.ocr_job(False)
 def ocr_job(self,verify=False):
  if self.busy():self.status.setText(self.t('busy'));return
  from .ocr import OCRManager
  self.control=JobControl();self.launch(lambda p:OCRManager().verify(p) if verify else OCRManager().download(p,self.control),lambda _:self.refresh_model_status())
 def format_bytes(self,value):
  value=float(value)
  for unit in ('B','KB','MB','GB','TB'):
   if value<1024 or unit=='TB':return f'{value:.1f} {unit}'
   value/=1024
 def refresh_model_status(self):
  from .ocr import OCRManager
  model=ModelManager().status();ocr=OCRManager().status();state=lambda ready:self.t('model_ready') if ready else self.t('model_not_ready');model_size=self.format_bytes(model['installed_bytes'])+((' / '+self.format_bytes(model['expected_bytes'])) if model['expected_bytes'] else '')
  model_lines=['EmbeddingGemma 2',f'{self.t("model_state")}: {state(model["ready"])}',f'{self.t("model_files")}: {model["files"]}/{model["total"] or "?"}',f'{self.t("model_size")}: {model_size}',f'{self.t("model_revision")}: {model["revision"] or "—"}',f'{self.t("model_capabilities")}: {self.t("model_text_code")}, {self.t("model_vision")}',f'{self.t("catalog_path")}: {ModelManager.path}'];ocr_lines=['OCR',f'{self.t("model_state")}: {state(ocr["ready"])}',f'{self.t("model_files")}: {ocr["files"]}/{ocr["total"]}',f'{self.t("model_size")}: {self.format_bytes(ocr["installed_bytes"])}',f'{self.t("ocr_profile")}: {ocr["profile"] or "—"}',f'{self.t("catalog_path")}: {OCRManager.path}']
  self.model_status.setPlainText('\n'.join(model_lines));self.ocr_status.setPlainText('\n'.join(ocr_lines))
 def settings_values(self):
  return dict(language=self.language.currentData(),theme=self.theme.currentData(),performance_preset=self.performance_preset.currentData(),index_workers=self.index_workers.currentData(),batch_size=self.batch.currentData(),index_queue_size=self.index_queue_size.currentData(),result_count=self.result_count.value(),provider=self.engine.currentText(),device=self.device.currentText(),dimension=int(self.dimension.currentText()),vision=self.vision.isChecked() and self.engine.currentText()=='gemma',ocr=self.ocr.isChecked(),keep_model_loaded=self.keep_model_loaded.isChecked(),auto_update=self.auto_update.isChecked(),auto_update_seconds=self.auto_update_seconds.value())
 def change_language(self,index):
  language=self.language.itemData(index)
  if not language or language==self.cfg.get('language'):return
  if self.busy():
   self.language.blockSignals(True);self.language.setCurrentIndex(self.language.findData(self.cfg.get('language')));self.language.blockSignals(False);self.status.setText(self.t('busy'));return
  self.cfg.update(self.settings_values());self.cfg['language']=language;atomic_json(ROOT/'config/settings.json',self.cfg);self.release_provider();self.build()
 def apply_performance_preset(self,index):
  key=self.performance_preset.itemData(index)
  if key not in PERFORMANCE_PRESETS:return
  self._applying_preset=True
  try:
   workers,batch,queue=PERFORMANCE_PRESETS[key];self.index_workers.setCurrentIndex(self.index_workers.findData(workers));self.batch.setCurrentIndex(self.batch.findData(batch));self.index_queue_size.setCurrentIndex(self.index_queue_size.findData(queue))
  finally:self._applying_preset=False
 def sync_performance_preset(self,*_):
  if self._applying_preset:return
  values=(self.index_workers.currentData(),self.batch.currentData(),self.index_queue_size.currentData());key=next((name for name,preset in PERFORMANCE_PRESETS.items() if preset==values),'custom');self.performance_preset.blockSignals(True);self.performance_preset.setCurrentIndex(self.performance_preset.findData(key));self.performance_preset.blockSignals(False)
 def save_settings(self):
  if self.busy():return
  self.cfg.update(self.settings_values());atomic_json(ROOT/'config/settings.json',self.cfg);self.release_provider();self.build()
 def configure_auto_update(self):
  self.auto_timer.stop()
  if self.cfg.get('auto_update'):self.auto_timer.start(max(15,int(self.cfg.get('auto_update_seconds',60)))*1000)
 def auto_update_catalogs(self):
  if self.busy() or not self.data:return
  self.control=JobControl();catalog_list=list(self.data)
  def work(progress):
   provider=self.get_provider();summary={}
   for c in catalog_list:
    self.control.check()
    try:
     index=Index(c,provider)
     if index.state()['status']=='incompatible':summary[c.root]={'rebuild_required':True};continue
     summary[c.root]=index.run(lambda value,root=c.root:progress(dict(catalog=root,details=value)),self.control,workers=self.cfg.get('index_workers',8),queue_size=self.cfg.get('index_queue_size',64))
    except FileNotFoundError as e:summary[c.root]={'offline':str(e)}
   return summary
  self.launch(work,lambda _:self.catalog_selected())
 def start_capture(self):
  if not self.busy():self.capture.start()
 def attach(self):
  if self.busy():return
  paths,_=QFileDialog.getOpenFileNames(self,self.t('attach'),'', 'Images (*.png *.jpg *.jpeg *.webp)');self.images.extend(paths);self.refresh_attachments()
 def attach_pixmap(self,image):
  p=self.session_temp/('query-'+uuid.uuid4().hex+'.png');image.save(str(p));self.temp_images.append(p);self.images.append(str(p));self.refresh_attachments()
 def paste(self):
  if self.busy():return
  clip=QApplication.clipboard()
  if clip.mimeData().hasImage():self.attach_pixmap(QPixmap.fromImage(clip.image()))
  elif isinstance(QApplication.focusWidget(),QLineEdit):QApplication.focusWidget().paste()
 def clear_images(self):
  if self.busy():return
  self.close_image_preview()
  self.images=[]
  for p in self.temp_images:p.unlink(missing_ok=True)
  self.temp_images=[];self.refresh_attachments()
 def remove_image(self,index):
  if self.busy() or not 0<=index<len(self.images):return
  value=self.images.pop(index);path=Path(value)
  if path in self.temp_images and value not in self.images:
   path.unlink(missing_ok=True);self.temp_images.remove(path)
  self.close_image_preview();self.refresh_attachments()
 def toggle_image_preview(self,path):
  if self.image_preview and self.image_preview.isVisible():self.close_image_preview();return
  pixmap=QPixmap(path)
  if pixmap.isNull():return
  self.preview_pixmap=pixmap;self.image_preview=ClickableImage(path,self.centralWidget());self.image_preview.setObjectName('imagePreview');self.image_preview.setStyleSheet('background:#080c12');self.image_preview.setAlignment(Qt.AlignCenter);self.image_preview.setCursor(Qt.PointingHandCursor);self.image_preview.setToolTip(Path(path).name);self.image_preview.clicked.connect(lambda _:self.close_image_preview());self.update_image_preview();self.image_preview.show();self.image_preview.raise_()
 def update_image_preview(self):
  if self.image_preview and self.preview_pixmap:
   self.image_preview.setGeometry(self.centralWidget().rect());self.image_preview.setPixmap(self.preview_pixmap.scaled(self.image_preview.size(),Qt.KeepAspectRatio,Qt.SmoothTransformation))
 def close_image_preview(self):
  if self.image_preview:self.image_preview.hide();self.image_preview.deleteLater()
  self.image_preview=None;self.preview_pixmap=None
 def resizeEvent(self,event):
  super().resizeEvent(event);self.update_image_preview();self.update_result_preview();self.position_view_button()
 def refresh_attachments(self):
  if not hasattr(self,'attachment_layout'):return
  while self.attachment_layout.count():
   item=self.attachment_layout.takeAt(0);widget=item.widget()
   if widget:widget.deleteLater()
  self.attachment_name_labels=[];self.attachment_thumbnail_labels=[];self.attachment_remove_buttons=[]
  for index,value in enumerate(self.images):
   path=Path(value);card=QFrame();card.setObjectName('attachmentCard');card.setFixedWidth(142);column=QVBoxLayout(card);column.setContentsMargins(5,5,5,5);column.setSpacing(4)
   image_box=QWidget();image_box.setFixedSize(130,78);thumbnail=ClickableImage(str(path),image_box);thumbnail.setObjectName('attachmentThumbnail');thumbnail.setGeometry(0,0,130,78);thumbnail.setAlignment(Qt.AlignCenter);thumbnail.setCursor(Qt.PointingHandCursor);thumbnail.clicked.connect(self.toggle_image_preview);pixmap=QPixmap(str(path))
   if pixmap.isNull():thumbnail.setText(self.t('image'))
   else:thumbnail.setPixmap(pixmap.scaled(thumbnail.size(),Qt.KeepAspectRatio,Qt.SmoothTransformation))
   remove=QPushButton('×',image_box);remove.setObjectName('attachmentRemove');remove.setStyleSheet('background:#d93232;color:white;border:1px solid #ff7777;border-radius:9px;padding:0;font-weight:700');remove.setFixedSize(20,20);remove.move(107,3);remove.setToolTip(self.t('remove_image'));remove.clicked.connect(lambda checked=False,i=index:self.remove_image(i));remove.raise_()
   name=QLabel();name.setObjectName('attachmentName');name.setAlignment(Qt.AlignCenter);name.setText(name.fontMetrics().elidedText(path.name,Qt.ElideMiddle,128));name.setToolTip(str(path));column.addWidget(image_box);column.addWidget(name);self.attachment_layout.addWidget(card);self.attachment_thumbnail_labels.append(thumbnail);self.attachment_name_labels.append(name);self.attachment_remove_buttons.append(remove)
  self.attachment_scroll.setVisible(bool(self.images))
 def dragEnterEvent(self,e):
  if e.mimeData().hasUrls():e.acceptProposedAction()
 def dropEvent(self,e):
  if self.busy():return
  for url in e.mimeData().urls():
   p=Path(url.toLocalFile())
   if p.is_dir():self.add_catalog(str(p))
   elif p.suffix.lower() in ('.png','.jpg','.jpeg','.webp'):self.images.append(str(p))
  self.refresh_attachments()
 def about(self):
  dlg=QDialog(self);dlg.setWindowTitle(self.t('about'));dlg.resize(620,470);box=QVBoxLayout(dlg);header=QHBoxLayout();logo=QLabel();logo.setPixmap(QPixmap(str(ROOT/'assets/logo.svg')).scaled(72,72,Qt.KeepAspectRatio,Qt.SmoothTransformation));header.addWidget(logo);heading=QLabel(f'<span style="font-size:24px;font-weight:700">SemanticX Find</span><br>{__version__}<br>{self.t("product_description")}');header.addWidget(heading,1);box.addLayout(header);view=QTextBrowser();view.setOpenExternalLinks(True);view.setHtml(f'<p><b>OreX — Founder of StableDif</b></p><p><a href="https://stabledif.ru/">stabledif.ru</a> · <a href="https://www.youtube.com/@StableDiff/videos">YouTube</a> · <a href="https://rutube.ru/channel/28380669/videos/">Rutube</a></p><p><b>{self.t("build_info")}</b><br>Python {sys.version.split()[0]} · Qt {qVersion()} · {platform.system()} {platform.release()}</p><p>{self.t("local_privacy")}</p><p>{self.t("alpha_notice")}</p>');box.addWidget(view);row=QHBoxLayout();row.addWidget(self.button('third_party',lambda:open_path(ROOT/'docs/THIRD_PARTY.md')));row.addWidget(self.button('copy_diagnostics',self.copy_diagnostics));row.addStretch();row.addWidget(self.button('close',dlg.accept));box.addLayout(row);dlg.exec()
 def diagnostics_text(self):
  from .ocr import OCRManager
  model=ModelManager().status();ocr=OCRManager().status()
  return '\n'.join(['SemanticX Find '+__version__,f'OS: {platform.platform()}',f'Python: {sys.version.split()[0]}',f'Qt: {qVersion()}',f'Provider: {self.cfg.get("provider")}',f'Device: {self.cfg.get("device")}',f'Dimension: {self.cfg.get("dimension")}',f'Embedding batch: {self.cfg.get("batch_size")}',f'Index workers: {self.cfg.get("index_workers",8)}',f'Preparation queue: {self.cfg.get("index_queue_size",64)}',f'Vision enabled: {self.cfg.get("vision",False)}',f'OCR enabled: {self.cfg.get("ocr",False)}',f'Catalogs: {len(self.data)}',f'EmbeddingGemma ready: {model["ready"]} ({model["files"]}/{model["total"]})',f'EmbeddingGemma revision: {model["revision"] or "none"}',f'OCR ready: {ocr["ready"]} ({ocr["files"]}/{ocr["total"]})',f'OCR profile: {ocr["profile"] or "none"}'])
 def copy_diagnostics(self):
  QApplication.clipboard().setText(self.diagnostics_text());self.status.setText(self.t('diagnostics_copied'))
 def closeEvent(self,e):
  if self.busy():e.ignore();return
  self.persist_window_geometry();self.clear_images();self.release_provider();self.shutdown_session_temp();e.accept()
 def restore_window_geometry(self):
  encoded=self.cfg.get('window_geometry','')
  if encoded:
   try:self.restoreGeometry(QByteArray.fromBase64(encoded.encode('ascii')))
   except Exception:pass
 def persist_window_geometry(self):
  self.cfg['window_geometry']=bytes(self.saveGeometry().toBase64()).decode('ascii');atomic_json(ROOT/'config/settings.json',self.cfg)
