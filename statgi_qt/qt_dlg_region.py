# -*- coding: utf-8 -*-
"""区域框选：全屏半透明覆盖层，拖一个矩形，返回屏幕绝对坐标。

从 qt_dialogs.py 拆出来的（第 2 批，纯搬运）。

⚠ `select_region()` 内部是 `while not sel._done:` 转事件 ——
   离屏测试**千万不要直接调它**，没人点会永久卡住。
   要测就自己造 `RegionSelector`。"""
import os
from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QGuiApplication, QPainter, QColor, QPen, QPixmap
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
                               QLabel, QPushButton, QFileDialog, QMessageBox,
                               QWidget, QFrame, QListWidget, QListWidgetItem,
                               QLineEdit, QCheckBox, QComboBox, QSlider,
                               QPlainTextEdit, QScrollArea)
import config_manager
import paths
from qt_theme import (TEXT, DIM, ACCENT, CARD, BG, BORDER, panel_alpha, label_qss,
                      btn_qss, combo_qss, slider_qss)
from qt_widgets import Card, set_btn_icon
from qt_icon import IconWidget


class RegionSelector(QWidget):
    def __init__(self, parent=None):
        super().__init__(None)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                            | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setCursor(Qt.CrossCursor)
        self._start = None
        self._cur = None
        self._done = False
        self._result = None

        # 盖住所有屏幕
        rect = QRect()
        for s in QGuiApplication.screens():
            rect = rect.united(s.geometry())
        self.setGeometry(rect)

        # 截一张全屏当"冻结背景"，避免遮罩下面还在动
        try:
            scr = QGuiApplication.primaryScreen()
            self._bg = scr.grabWindow(0)
        except Exception:
            self._bg = None

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        if self._bg is not None:
            p.drawPixmap(self.rect(), self._bg)
        p.fillRect(self.rect(), QColor(0, 0, 0, 110))
        if self._start and self._cur:
            r = QRect(self._start, self._cur).normalized()
            p.setCompositionMode(QPainter.CompositionMode_Clear)
            p.fillRect(r, Qt.transparent)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            p.setPen(QPen(QColor(ACCENT), 2))
            p.drawRect(r)

    def mousePressEvent(self, e):
        self._start = e.position().toPoint()
        self._cur = self._start
        self.update()

    def mouseMoveEvent(self, e):
        if self._start:
            self._cur = e.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, e):
        if self._start and self._cur:
            r = QRect(self._start, self._cur).normalized()
            if r.width() > 4 and r.height() > 4:
                self._result = QRect(self.x() + r.x(), self.y() + r.y(),
                                     r.width(), r.height())
        self._done = True
        self.close()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self._done = True
            self.close()


def select_region(parent=None):
    """弹出全屏框选，返回 QRect（屏幕绝对坐标）或 None

    做法：转 Qt 事件循环直到用户松手或按 Esc，再读结果。
    """
    import time
    sel = RegionSelector(parent)
    sel.show()
    sel.raise_()
    sel.activateWindow()
    while not sel._done:
        QGuiApplication.processEvents()
        time.sleep(0.01)
    return sel._result
