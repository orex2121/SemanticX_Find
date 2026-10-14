"""Offscreen tests of desktop state and the real QThread lifecycle."""
import csv,json,os,shutil,time
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import pytest
from PIL import Image
from filelock import FileLock
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from semanticx import ui,engine,paths

@pytest.fixture(scope='module')
def app():
 return QApplication.instance() or QApplication([])
@pytest.fixture
def window(tmp_path,monkeypatch,app):
 source=paths.ROOT
 for name in ('locales','assets'):shutil.copytree(source/name,tmp_path/name)
 for module in (paths,engine,ui):monkeypatch.setattr(module,'ROOT',tmp_path)
 paths.bootstrap();w=ui.Window();w.show();app.processEvents()
 yield w
 wait_idle(w);w.close();app.processEvents()
def wait_idle(w):
 deadline=time.monotonic()+15
 while w.busy() and time.monotonic()<deadline:QTest.qWait(10)
 assert not w.busy()
def test_rebuild_preserves_state(window,app):
 w=window;image=paths.ROOT/'reference-image-with-a-long-descriptive-name.png';Image.new('RGB',(80,40),'navy').save(image);w.query.setText('Qwen редактирование');w.minimum.setValue(.25);w.modified.setCurrentIndex(w.modified.findData(7));w.max_size.setValue(25);w.tabs.setCurrentIndex(3);w.images=[str(image)];w.build()
 assert w.query.text()=='Qwen редактирование'
 assert 'EmbeddingGemma 2' in w.model_status.toPlainText() and 'OCR' in w.ocr_status.toPlainText()
 assert w.minimum.value()==.25 and w.tabs.currentIndex()==3 and w.modified.currentData()==7 and w.max_size.value()==25
 assert not w.attachment_scroll.isHidden() and len(w.attachment_name_labels)==1
 assert w.attachment_name_labels[0].toolTip()==str(image)
 assert w.attachment_name_labels[0].text()!=image.name
 assert not w.attachment_thumbnail_labels[0].pixmap().isNull()
 assert '#d93232' in w.attachment_remove_buttons[0].styleSheet()
 w.attachment_thumbnail_labels[0].clicked.emit(str(image));app.processEvents()
 assert w.image_preview is not None and w.image_preview.isVisible()
 w.image_preview.clicked.emit(str(image));app.processEvents()
 assert w.image_preview is None
 w.clear_images();assert w.attachment_scroll.isHidden()
def test_remove_one_attached_image(window,tmp_path,app):
 w=window;first=tmp_path/'first.png';second=tmp_path/'second.png';Image.new('RGB',(20,20),'red').save(first);Image.new('RGB',(20,20),'blue').save(second);w.images=[str(first),str(second)];w.refresh_attachments()
 assert len(w.attachment_remove_buttons)==2
 w.attachment_remove_buttons[0].click();app.processEvents()
 assert w.images==[str(second)] and len(w.attachment_thumbnail_labels)==1
def test_image_result_has_thumbnail_and_expandable_preview(window,tmp_path,app):
 w=window;image=tmp_path/'visual-result.png';Image.new('RGB',(320,180),'purple').save(image);w.results=[{'path':str(image),'relative_path':'visual-result.png','signals':{'visual':.9},'text':'Image visual content','size':image.stat().st_size,'mtime_ns':image.stat().st_mtime_ns}];w.refresh_result_items();app.processEvents()
 assert not w.list.item(0).icon().isNull() and w.list.item(0).sizeHint().height()>=80
 assert not w.result_preview.isHidden() and not w.result_preview.pixmap().isNull()
 w.result_preview.clicked.emit(str(image));app.processEvents();assert w.image_preview is not None and w.image_preview.isVisible()
 w.image_preview.clicked.emit(str(image));app.processEvents();assert w.image_preview is None
def test_result_view_switches_between_thumbnail_grids_and_list(window,tmp_path,app):
 w=window;image=tmp_path/'tile-image.png';Image.new('RGB',(320,240),'orange').save(image);w.results=[{'path':str(image),'relative_path':'folder/tile-image.png','signals':{},'text':'','size':image.stat().st_size,'mtime_ns':image.stat().st_mtime_ns}];w.refresh_result_items()
 w.set_result_view('normal');app.processEvents();assert w.list.viewMode()==ui.QListView.IconMode and w.list.iconSize()==ui.QSize(150,150) and w.list.item(0).text()=='tile-image.png' and w.list.item(0).toolTip()==str(image)
 assert w.list.verticalScrollMode()==ui.QAbstractItemView.ScrollPerPixel and w.list.verticalScrollBar().singleStep()>=150
 assert w.view_button.parent() is w.list and w.view_button.y()==8 and w.view_button.x()>w.list.width()//2 and 'rgba(32,52,73,205)' in w.view_button.styleSheet()
 fixed_position=w.view_button.pos();w.list.verticalScrollBar().setValue(w.list.verticalScrollBar().maximum());app.processEvents();assert w.view_button.pos()==fixed_position
 assert paths.settings()['result_view']=='normal' and w.result_view_actions['normal'].isChecked()
 w.build();app.processEvents();assert w.result_view_mode=='normal' and w.list.viewMode()==ui.QListView.IconMode and w.list.item(0).text()=='tile-image.png'
 w.set_result_view('list');app.processEvents();text=w.list.item(0).text();assert w.list.viewMode()==ui.QListView.ListMode and w.t('result_score') in text and 'tile-image.png' in text and w.t('file_size') in text and 'folder/tile-image.png' not in text and paths.settings()['result_view']=='list'
def test_finished_callback_can_start_next_job(window):
 w=window;seen=[]
 def done(value):
  assert not w.busy();seen.append(value);w.launch(lambda progress:2,seen.append)
 w.launch(lambda progress:1,done);wait_idle(w)
 assert seen==[1,2] and w.jobs==[]
def test_none_job_result_does_not_leak_into_status(window):
 w=window;w.launch(lambda progress:None);wait_idle(w)
 assert w.status.text()==w.t('done')
def test_cancel_does_not_apply_search_results(window):
 w=window;w.results=[{'old':True}]
 def work(progress):raise engine.Cancelled()
 w.launch(work,w.search_done);wait_idle(w)
 assert w.results==[{'old':True}] and w.status.text()==w.t('cancelled')
def test_model_is_released_after_job_when_memory_retention_is_disabled(window):
 w=window
 class Provider:
  def __init__(self):self.unloaded=False
  def unload(self):self.unloaded=True
 provider=Provider();w.provider=provider;w.cfg['keep_model_loaded']=False;w.launch(lambda progress:1);wait_idle(w)
 assert provider.unloaded and w.provider is None
def test_error_then_retry(window):
 w=window
 def fail(progress):raise ValueError('broken')
 w.launch(fail);wait_idle(w);assert 'ValueError: broken'==w.status.text()
 seen=[];w.launch(lambda progress:3,seen.append);wait_idle(w);assert seen==[3]
def test_locale_and_theme(window):
 w=window;w.query.setText('persistent');w.language.setCurrentIndex(w.language.findData('ru'));w.theme.setCurrentIndex(w.theme.findData('light'));w.save_settings()
 assert w.query.text()=='persistent' and w.tabs.tabText(0)=='Поиск' and 'QPushButton:pressed' in w.styleSheet()
 assert paths.settings()['language']=='ru' and paths.settings()['theme']=='light'
def test_window_geometry_is_persisted_and_restored(window,app):
 w=window;w.resize(1000,700);app.processEvents();expected=w.size();w.persist_window_geometry();assert paths.settings().get('window_geometry')
 w.resize(800,600);w.restore_window_geometry();app.processEvents()
 assert w.size()==expected
def test_search_history_is_persistent_unique_and_clearable(window):
 w=window;w.record_search('first query');w.record_search('Second query');w.record_search('FIRST QUERY')
 assert paths.settings()['search_history']==['FIRST QUERY','Second query']
 w.history.setCurrentIndex(w.history.findData('Second query'));assert w.query.text()=='Second query'
 w.history.setCurrentIndex(w.history.findData('__clear__'))
 assert paths.settings()['search_history']==[] and w.history.count()==1
def test_search_mode_selector_defaults_to_vision_first_and_survives_rebuild(window):
 w=window;assert [w.search_mode.itemData(i) for i in range(w.search_mode.count())]==['vision_only','text_only','vision_first','text_first'];assert w.search_mode.currentData()=='vision_first'
 assert ui.search_source_order('vision_first')==('vision','text') and ui.search_source_order('text_first')==('text','vision')
 w.search_mode.setCurrentIndex(w.search_mode.findData('text_first'));w.build();assert w.search_mode.currentData()=='text_first'
def test_catalog_scope_supports_multiple_checked_catalogs(window,tmp_path):
 w=window;first=tmp_path/'first-catalog';second=tmp_path/'second-catalog';first.mkdir();second.mkdir();plain=engine.register(first);visual=engine.register(second);base=Path(visual.index_path);paths.atomic_json(base/'index.json',{'identity':{'visual':True}});(base/'manifest.sqlite').touch();w.data=[plain,visual];w.build();ids=[c.id for c in w.data]
 assert w.scope.selected_ids()==ids and w.scope.itemData(0,Qt.CheckStateRole)==Qt.Checked and w.scope.lineEdit().text()==w.t('all_catalogs')
 assert not w.scope.itemData(1,ui.VISION_ROLE) and w.scope.itemData(2,ui.VISION_ROLE)
 assert w.catalog_list.item(0).icon().isNull() and not w.catalog_list.item(1).icon().isNull()
 w.scope.set_selected_ids([ids[0]]);assert w.scope.selected_ids()==[ids[0]] and w.scope.itemData(0,Qt.CheckStateRole)==Qt.PartiallyChecked and w.scope.lineEdit().text()=='first-catalog'
 w.build();assert w.scope.selected_ids()==[ids[0]]
 w.save_catalog_selection();assert paths.settings()['selected_catalogs']==[ids[0]]
 w.scope.set_selected_ids(None);w.restore_view({});assert w.scope.selected_ids()==[ids[0]]
 QTest.mouseClick(w.scope.lineEdit(),Qt.LeftButton);app=QApplication.instance();app.processEvents();assert w.scope.view().isVisible();w.scope.hidePopup()
 w.scope._apply_toggle(0,Qt.Unchecked);assert w.scope.selected_ids()==[] and w.scope.lineEdit().text()==w.t('no_catalogs_selected') and paths.settings()['selected_catalogs']==[]
def test_file_type_filter_supports_multiple_persistent_choices(window):
 w=window;available=[w.extension.itemData(row) for row in range(1,w.extension.count())]
 assert w.extension.selected_extensions()==available and w.extension.lineEdit().text()==w.t('all_types')
 w.extension.set_selected_ids(['.jpg','.pdf']);w.save_file_type_selection()
 assert w.extension.selected_extensions()==['.jpg','.pdf'] and w.extension.lineEdit().text()==w.t('types_selected').format(count=2) and paths.settings()['selected_file_types']==['.jpg','.pdf']
 w.extension.set_selected_ids(None);w.restore_view({});assert w.extension.selected_extensions()==['.jpg','.pdf']
 w.extension._apply_toggle(0,Qt.Unchecked);assert w.extension.selected_extensions()==[] and w.extension.lineEdit().text()==w.t('no_types_selected') and paths.settings()['selected_file_types']==[]
def test_diagnostics_are_copyable_and_exclude_private_queries(window):
 w=window;w.query.setText('private search phrase');text=w.diagnostics_text()
 assert 'SemanticX Find 0.3.19-alpha' in text and 'EmbeddingGemma ready:' in text and 'private search phrase' not in text
 w.copy_diagnostics();assert QApplication.clipboard().text()==text and w.status.text()==w.t('diagnostics_copied')
def test_persistent_favorites(window,tmp_path):
 w=window;path=tmp_path/'favorite.json';path.write_text('{}');w.results=[{'path':str(path),'relative_path':'favorite.json','signals':{},'text':''}];w.refresh_result_items();w.toggle_favorite()
 assert paths.settings()['favorites']==[str(path.resolve())] and w.list.item(0).text().startswith('★ ') and w.favorites_list.count()==1
 w.favorite_action('copy');assert QApplication.clipboard().text()==str(path.resolve())
 w.favorite_action('copy_name');assert QApplication.clipboard().text()=='favorite.json'
 w.favorite_action('copy_folder');assert QApplication.clipboard().text()==str(tmp_path)
 w.favorite_action('catalog');assert w.status.text()==w.t('favorite_not_catalog')
 path.unlink();w.refresh_favorites();assert w.favorites_list.item(0).text().startswith('⚠ ')
 w.favorite_action('remove');assert paths.settings()['favorites']==[] and w.favorites_list.count()==0 and not w.list.item(0).text().startswith('★ ')
def test_file_drag_mime_supports_multiple_existing_files(window,tmp_path):
 w=window;first=tmp_path/'first.json';second=tmp_path/'second.json';first.write_text('{}');second.write_text('{}');missing=tmp_path/'missing.json';w.results=[{'path':str(path),'relative_path':path.name,'signals':{},'text':''} for path in (first,second,missing)];w.refresh_result_items()
 for i in range(w.list.count()):w.list.item(i).setSelected(True)
 mime=w.list.drag_mime();urls=[Path(url.toLocalFile()) for url in mime.urls()]
 assert urls==[first.resolve(),second.resolve()] and str(first.resolve()) in mime.text() and str(missing) not in mime.text()
 w.list.clearSelection();w.list.setCurrentRow(1);mime=w.list.drag_mime();assert [Path(url.toLocalFile()) for url in mime.urls()]==[second.resolve()]

def test_catalog_stats_are_not_limited_by_visible_file_rows(window,tmp_path):
 w=window;root=tmp_path/'large-catalog';root.mkdir();cat=engine.register(root);index=engine.Index(cat);db=index.connect()
 try:
  db.executemany("INSERT INTO files(relative_path,size,mtime_ns,content_hash,extractor_version,status,last_indexed,error) VALUES(?,?,?,?,?,?,?,?)",[(f'{i:04}.txt',1,i,str(i),'test','ready',float(i),None) for i in range(2005)]);db.commit()
 finally:db.close()
 w.data=[cat];engine.save_catalogs(w.data);w.build();w.catalog_list.setCurrentRow(0);w.catalog_selected()
 assert w.catalog_file_list.count()==2000 and f'{w.t("catalog_files")}: 2005' in w.catalog_details.toPlainText() and f'{w.t("catalog_ready")}: 2005' in w.catalog_details.toPlainText()
 assert Path(w.catalog_file_list.item(0).data(Qt.UserRole)).is_absolute()
def test_search_results_export_csv_and_json(window,tmp_path):
 w=window;source=tmp_path/'результат.json';w.results=[dict(path=str(source),relative_path='папка/результат.json',catalog_id='cat-1',score=.875,size=123,mtime_ns=1700000000000000000,signals={'semantic':.9,'lexical':.5},text='private indexed contents')];csv_path=tmp_path/'results.csv';json_path=tmp_path/'results.json';w.export_results(csv_path);w.export_results(json_path)
 with csv_path.open(encoding='utf-8-sig',newline='') as stream:rows=list(csv.DictReader(stream))
 exported=json.loads(json_path.read_text(encoding='utf-8'))
 assert rows[0]['filename']=='результат.json' and rows[0]['signal_semantic']=='0.9' and exported[0]['relative_path']=='папка/результат.json'
 assert 'private indexed contents' not in csv_path.read_text(encoding='utf-8-sig') and 'private indexed contents' not in json_path.read_text(encoding='utf-8') and not list(tmp_path.glob('*.part'))
def test_vision_mode_indicator_and_catalog_configuration(window,tmp_path,monkeypatch):
 w=window;model_status=lambda ready:dict(ready=ready,files=14,total=14,installed_bytes=100,expected_bytes=100,revision='test');assert w.vision_state()=='disabled' and w.vision_badge is None;monkeypatch.setattr(ui.ModelManager,'status',lambda self:model_status(True));w.cfg.update(provider='gemma',vision=True);w.refresh_vision_badge();assert w.vision_state()=='ready';monkeypatch.setattr(ui.ModelManager,'status',lambda self:model_status(False));w.refresh_vision_badge();assert w.vision_state()=='unavailable'
 root=tmp_path/'visual-catalog';root.mkdir();cat=engine.register(root);w.data=[cat];engine.save_catalogs(w.data);w.build();w.apply_catalog_settings(w.data[0],{'visual':True});assert engine.catalogs()[0].visual and w.status.text()==w.t('catalog_saved_rebuild')
def test_search_controls_have_visible_explanations(window):
 w=window;labels='\n'.join(label.text() for label in w.findChildren(ui.QLabel));assert w.t('catalog_scope_title') in labels and w.t('query_title') in labels and '<br>' not in labels
 assert not hasattr(w,'path_filter') and not hasattr(w,'node_filter') and not hasattr(w,'model_filter')
 assert '#39a6ff' in w.query.styleSheet() and '#39a6ff' in w.scope.styleSheet() and '#57b8ff' in w.search_button.styleSheet() and '#55d39a' in w.capture_button.styleSheet()
 assert [w.extension.itemData(i) for i in range(1,w.extension.count())][:11]==['.json','.png','.jpg','.jpeg','.webp','.txt','.md','.html','.htm','.pdf','.py']
 assert w.t('clear_images') not in [button.text() for button in w.findChildren(ui.QPushButton)]
def test_model_actions_are_beside_each_model_and_vision_help_is_compact(window):
 w=window;assert 'EmbeddingGemma 2' in w.model_status.toPlainText() and 'OCR' in w.ocr_status.toPlainText()
 assert [w.model_download_button.text(),w.model_verify_button.text(),w.ocr_download_button.text(),w.ocr_verify_button.text()]==[w.t('download'),w.t('verify'),w.t('download'),w.t('verify')]
 assert w.model_download_button.y()==w.model_verify_button.y() and w.ocr_download_button.y()==w.ocr_verify_button.y()
 assert not w.vision_help.wordWrap() and w.settings_form.labelForField(w.vision_help) is w.vision and w.t('vision_help').startswith('Creates')
 assert w.settings_form.labelForField(w.ocr_help) is w.ocr and w.settings_form.labelForField(w.keep_model_help) is w.keep_model_loaded and w.keep_model_loaded.isChecked() and 'VRAM' in w.keep_model_help.text()
 w.keep_model_loaded.setChecked(False);w.save_settings();assert paths.settings()['keep_model_loaded'] is False and not w.keep_model_loaded.isChecked()
def test_performance_settings_are_bounded_lists_with_tooltips(window):
 w=window;assert [w.index_workers.itemData(i) for i in range(w.index_workers.count())]==[2,4,8,16,32]
 assert [w.batch.itemData(i) for i in range(w.batch.count())]==[32,64,128,256,512] and w.batch.currentData()==128
 assert [w.index_queue_size.itemData(i) for i in range(w.index_queue_size.count())]==[16,32,64,128,256,512]
 controls=(w.language,w.theme,w.index_workers,w.batch,w.index_queue_size,w.result_count,w.engine,w.device,w.dimension,w.vision,w.ocr,w.keep_model_loaded,w.auto_update,w.auto_update_seconds)
 assert all(control.toolTip().strip() for control in controls) and 'does not affect' in w.result_count.toolTip()
 w.index_workers.setCurrentIndex(w.index_workers.findData(16));w.batch.setCurrentIndex(w.batch.findData(256));w.index_queue_size.setCurrentIndex(w.index_queue_size.findData(128));w.save_settings();saved=paths.settings()
 assert (saved['index_workers'],saved['batch_size'],saved['index_queue_size'])==(16,256,128)
def test_performance_presets_apply_linked_values_and_manual_changes_become_custom(window):
 w=window;assert [w.performance_preset.itemData(i) for i in range(w.performance_preset.count())]==['custom','minimum','basic','balanced','high','maximum']
 w.performance_preset.setCurrentIndex(w.performance_preset.findData('maximum'));assert (w.index_workers.currentData(),w.batch.currentData(),w.index_queue_size.currentData())==(32,512,256)
 assert w.performance_preset.toolTip()==w.t('performance_preset_help') and w.performance_preset.itemData(w.performance_preset.currentIndex(),Qt.ToolTipRole)==w.t('preset_maximum_help')
 w.batch.setCurrentIndex(w.batch.findData(128));assert w.performance_preset.currentData()=='custom'
def test_language_change_retranslates_the_entire_interface_immediately(window,app):
 w=window;w.tabs.setCurrentIndex(3);w.language.setCurrentIndex(w.language.findData('fr'));app.processEvents()
 assert w.cfg['language']=='fr' and paths.settings()['language']=='fr' and w.tabs.tabText(0)=='Rechercher' and w.tabs.tabText(1)=='Catalogues'
 assert w.catalog_buttons['update'].text()==w.t('update') and w.catalog_buttons['update'].toolTip()==w.t('catalog_tip_update')
 assert w.settings_form.labelForField(w.performance_preset).text()==w.t('performance_preset') and w.performance_preset.toolTip()==w.t('performance_preset_help')
 assert w.tabs.currentIndex()==3
def test_help_and_version_are_in_bottom_footer(window):
 w=window;assert w.menuBar().isHidden() and w.version_label.text()=='0.3.19-alpha' and w.help_button.text()==w.t('information')
 assert [action.text() for action in w.help_button.menu().actions()]==[w.t('about'),w.t('guide')]
def test_busy_buttons_animate_and_restore(window):
 w=window;button=w.search_button;original=button.text();w.start_button_activity(button)
 assert button.property('busy') is True and not button.isEnabled() and button.text()!=original
 w.advance_button_activity();assert '●' in button.text()
 w.stop_button_activity(button);assert button.property('busy') is False and button.isEnabled() and button.text()==original
 assert ':pressed' in button.styleSheet() and '[busy="true"]' in button.styleSheet()
def test_session_temp_cleanup_respects_active_instances(window):
 w=window;temp=paths.ROOT/'temp';stale=temp/'session-stale';stale.mkdir();(stale/'query-old.png').write_bytes(b'x');active=temp/'session-active';active.mkdir();lock=FileLock(str(active/'active.lock'));lock.acquire(timeout=0);legacy=temp/'query-legacy.png';legacy.write_bytes(b'x');os.utime(legacy,(time.time()-90000,time.time()-90000));recent=temp/'query-recent.png';recent.write_bytes(b'x')
 w.cleanup_stale_temp_sessions();assert not stale.exists() and active.exists() and not legacy.exists() and recent.exists()
 lock.release();w.cleanup_stale_temp_sessions();assert not active.exists()
 pixmap=QPixmap(12,12);pixmap.fill(Qt.red);w.attach_pixmap(pixmap);capture=Path(w.images[-1]);assert capture.parent==w.session_temp and capture.exists();w.clear_images();assert not capture.exists() and w.session_temp.exists()
def test_automatic_incremental_index_update(window):
 w=window;root=paths.ROOT/'automatic';root.mkdir();(root/'new.txt').write_text('automatic indexing content');cat=engine.register(root);w.data=[cat];engine.save_catalogs(w.data);w.auto_update_catalogs();wait_idle(w)
 assert [x['relative_path'] for x in engine.Index(cat).files()] == ['new.txt']
 w.cfg.update(auto_update=True,auto_update_seconds=15);w.configure_auto_update();assert w.auto_timer.isActive() and w.auto_timer.interval()==15000;w.auto_timer.stop()
def test_catalog_duplicate_browser(window):
 w=window;root=paths.ROOT/'duplicates';root.mkdir();(root/'copy-a.txt').write_text('identical content');(root/'copy-b.txt').write_text('identical content');(root/'unique.txt').write_text('different content');cat=engine.register(root);w.data=[cat];engine.save_catalogs(w.data);engine.Index(cat).run();w.build();w.catalog_list.setCurrentRow(0);w.show_duplicates()
 assert w.catalog_file_list.count()==2 and 'Duplicate groups: 1' in w.catalog_details.toPlainText() and all(w.catalog_file_list.item(i).data(Qt.UserRole) for i in range(2))
def test_catalogs_details_and_files_use_horizontal_movable_splitters(window):
 w=window;assert w.catalog_splitter.orientation()==Qt.Horizontal and w.catalog_content_splitter.orientation()==Qt.Horizontal
 assert w.catalog_splitter.handle(1).isEnabled() and w.catalog_content_splitter.handle(1).isEnabled() and w.catalog_list.maximumHeight()>10000
 labels='\n'.join(label.text() for label in w.findChildren(ui.QLabel));assert all(w.t(key) in labels for key in ('catalogs_panel_title','catalog_info_title','indexed_files_title'))
def test_catalog_buttons_have_detailed_tooltips(window):
 w=window;expected={'add','catalog_settings','update','rebuild','remove','pause','cancel','open_file','open_folder','copy_path'}
 assert set(w.catalog_buttons)==expected
 for key in expected:
  tooltip=w.catalog_buttons[key].toolTip();assert tooltip==w.t('catalog_tip_'+key) and len(tooltip)>20
 assert 'unchanged' in w.catalog_buttons['update'].toolTip() and 'remain on disk' in w.catalog_buttons['remove'].toolTip()
 assert w.t('clear_filter') not in [button.text() for button in w.findChildren(ui.QPushButton)] and w.t('find_duplicates') not in [button.text() for button in w.findChildren(ui.QPushButton)]
def test_text_only_results_temporarily_switch_to_list(window,tmp_path):
 w=window;w.cfg['result_view']='normal';w.set_result_view('normal',False);text=tmp_path/'workflow.json';text.write_text('{}');base=dict(relative_path='workflow.json',catalog_id='cat',score=1.,signals={},text='',size=2,mtime_ns=text.stat().st_mtime_ns)
 w.search_done([dict(base,path=str(text))]);assert w.result_view_mode=='list' and w.cfg['result_view']=='normal'
 image=tmp_path/'preview.png';Image.new('RGB',(20,20),'blue').save(image);w.search_done([dict(base,path=str(image),relative_path='preview.png')]);assert w.result_view_mode=='normal'
def test_real_workflow_search_and_filter(window,monkeypatch):
 w=window;root=paths.ROOT/'workflows';root.mkdir();fixtures=Path(__file__).parent/'fixtures'
 for p in fixtures.glob('*.json'):
  if p.name!='SOURCES.json':shutil.copy(p,root)
 cat=engine.register(root);w.data=[cat];engine.save_catalogs(w.data);engine.Index(cat).run();w.build();w.catalog_list.setCurrentRow(0);w.catalog_selected();catalog_text=w.catalog_details.toPlainText()
 assert 'Index status: Ready' in catalog_text and 'Semantic chunks' in catalog_text and '{' not in catalog_text and w.catalog_file_list.count()==4
 w.catalog_file_list.setCurrentRow(0);w.catalog_file_action('copy');assert QApplication.clipboard().text()==str(root/w.catalog_file_list.currentItem().data(Qt.UserRole))
 w.catalog_file_action('copy_name');assert QApplication.clipboard().text()==Path(w.catalog_file_list.currentItem().data(Qt.UserRole)).name
 w.catalog_file_action('copy_folder');assert QApplication.clipboard().text()==str(root/Path(w.catalog_file_list.currentItem().data(Qt.UserRole)).parent)
 opened=[];monkeypatch.setattr(ui,'open_path',lambda path,select=False:opened.append((str(path),select)));w.catalog_file_list.itemDoubleClicked.emit(w.catalog_file_list.currentItem());assert opened[-1][0].startswith(str(root))
 w.query.setText('Qwen image editing');w.search();wait_idle(w)
 assert Path(w.results[0]['path']).name=='qwen_edit.json'
 assert 'File size:' in w.details.toPlainText() and 'Modified:' in w.details.toPlainText()
 w.result_action('copy_name');assert QApplication.clipboard().text()=='qwen_edit.json'
 w.result_action('copy_folder');assert QApplication.clipboard().text()==str(root)
 w.list.itemDoubleClicked.emit(w.list.currentItem());assert opened[-1]==(w.results[0]['path'],False)
 assert 'Text match' in w.details.toPlainText()
