"""Recovered multi-screen capture; Windows mixed-DPI behavior needs validation."""
import math
from PySide6.QtCore import Qt,QRect,Signal,QObject,QTimer
from PySide6.QtGui import QColor,QPainter,QPen,QPixmap
from PySide6.QtWidgets import QWidget,QApplication
class Overlay(QWidget):
 def __init__(self,screen,controller):
  super().__init__();self.screen_ref=screen;self.controller=controller;self.frame=screen.grabWindow(0);self.setWindowFlags(Qt.FramelessWindowHint|Qt.WindowStaysOnTopHint|Qt.Tool);self.setGeometry(screen.geometry());self.setCursor(Qt.CrossCursor);self.setMouseTracking(True)
 def paintEvent(self,event):
  p=QPainter(self);p.drawPixmap(self.rect(),self.frame);p.fillRect(self.rect(),QColor(0,0,0,110));rect=self.controller.selection()
  if rect:p.setPen(QPen(QColor('#70e0bd'),2));p.drawRect(rect.translated(-self.geometry().topLeft()))
 def mousePressEvent(self,e):self.controller.start_point=e.globalPosition().toPoint();self.controller.end_point=self.controller.start_point;self.grabMouse()
 def mouseMoveEvent(self,e):
  if self.controller.start_point is not None:self.controller.end_point=e.globalPosition().toPoint();self.controller.repaint()
 def mouseReleaseEvent(self,e):self.releaseMouse();self.controller.end_point=e.globalPosition().toPoint();self.controller.capture_region()
 def keyPressEvent(self,e):
  if e.key()==Qt.Key_Escape:self.controller.finish(None)
class Capture(QObject):
 done=Signal(object)
 def __init__(self,parent):super().__init__(parent);self.window=parent;self.overlays=[];self.start_point=None;self.end_point=None
 def start(self):self.start_point=None;self.end_point=None;self.window.hide();QTimer.singleShot(250,self.show_overlays)
 def show_overlays(self):
  self.overlays=[Overlay(screen,self) for screen in QApplication.screens()]
  for o in self.overlays:o.show();o.activateWindow()
 def selection(self):return QRect(self.start_point,self.end_point).normalized() if self.start_point is not None and self.end_point is not None else None
 def repaint(self):
  for o in self.overlays:o.update()
 def capture_region(self):
  rect=self.selection()
  if rect is None or rect.width()<4 or rect.height()<4:self.finish(None);return
  involved=[o for o in self.overlays if o.geometry().intersects(rect)]
  if not involved:self.finish(None);return
  scale=max(o.frame.devicePixelRatio() for o in involved)
  if rect.width()*rect.height()*scale*scale>100_000_000:self.finish(None);return
  result=QPixmap(math.ceil(rect.width()*scale),math.ceil(rect.height()*scale));result.setDevicePixelRatio(scale);result.fill(Qt.transparent);p=QPainter(result)
  for o in involved:
   intersect=o.geometry().intersected(rect);source=intersect.translated(-o.geometry().topLeft());ratio=o.frame.devicePixelRatio();cropped=o.frame.copy(QRect(round(source.x()*ratio),round(source.y()*ratio),round(source.width()*ratio),round(source.height()*ratio)));p.drawPixmap(intersect.translated(-rect.topLeft()),cropped)
  p.end();self.finish(result)
 def finish(self,image):
  for o in self.overlays:o.close();o.deleteLater()
  self.overlays=[];self.window.show();self.window.activateWindow()
  if image is not None:self.done.emit(image)
