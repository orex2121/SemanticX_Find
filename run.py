from pathlib import Path
import traceback


def report_startup_error(error):
 root=Path(__file__).resolve().parent;log=root/'logs'/'startup-error.log';log.parent.mkdir(parents=True,exist_ok=True)
 details=''.join(traceback.format_exception(type(error),error,error.__traceback__))
 log.write_text(details,encoding='utf-8')
 message=f'SemanticX Find could not start.\n\n{error}\n\nDetails were saved to:\n{log}'
 try:
  from PySide6.QtWidgets import QApplication,QMessageBox
  app=QApplication.instance() or QApplication([]);QMessageBox.critical(None,'SemanticX Find - startup error',message)
 except Exception:
  try:
   import ctypes;ctypes.windll.user32.MessageBoxW(0,message,'SemanticX Find - startup error',0x10)
  except Exception:pass


if __name__=='__main__':
 try:
  import sys
  from semanticx.paths import bootstrap
  bootstrap()
  from PySide6.QtWidgets import QApplication
  from semanticx.ui import Window
  app=QApplication(sys.argv);app.setApplicationName('SemanticX Find');window=Window();window.show();raise SystemExit(app.exec())
 except SystemExit:raise
 except Exception as error:
  report_startup_error(error);raise SystemExit(1)
