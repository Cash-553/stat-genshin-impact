# -*- coding: utf-8 -*-
"""侧栏的导航按钮：图标 + 名字，悬停弹动、选中高亮。

从 qt_window.py 拆出来的（第 3 批，纯搬运）。

⚠ **这个文件被 qt_bar_editor.py 顶层依赖着**
   （`from qt_window import NavButton`，第 26 行）。
   qt_window.py 里有转发，别删。"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import QFrame, QLabel, QHBoxLayout
from qt_theme import label_qss
import qt_theme as T
from qt_icon import IconWidget, HoverHelper


# ============================================================
#  侧栏的一项
# ============================================================
class NavButton(QFrame):
    """侧栏的一项：图标 + 名字。

    鼠标放到整项上 → 图标弹一下；选中时底色高亮、文字和图标转成强调色。
    """

    clicked = Signal()

    def __init__(self, parent, icon, text, height=40):
        super().__init__(parent)
        self.setFixedHeight(height)
        self.setCursor(Qt.PointingHandCursor)
        self._active = False
        self._hover = False

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 12, 0)
        lay.setSpacing(10)

        self.icon_widget = IconWidget(self, name=icon, size=18, role="TEXT")
        lay.addWidget(self.icon_widget)

        self.label = QLabel(text)
        self.label.setStyleSheet(label_qss(T.TEXT, 14))
        self.label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        lay.addWidget(self.label)
        lay.addStretch(1)

        self._hh = HoverHelper(self, self._on_hover)

    def _on_hover(self, on):
        self._hover = on
        self.icon_widget.set_hover(on)
        self.update()

    def set_active(self, active):
        self._active = bool(active)
        self.label.setStyleSheet(
            label_qss(T.ACCENT if self._active else T.TEXT, 14))
        self.icon_widget.set_color(role="ACCENT" if self._active else "TEXT")
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()
            e.accept()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        if self._active:
            c = QColor(T.ACCENT)
            c.setAlpha(45)
            p.setBrush(c)
            p.drawRoundedRect(self.rect(), 8, 8)
        elif self._hover:
            p.setBrush(QColor(255, 255, 255, 28))
            p.drawRoundedRect(self.rect(), 8, 8)
        p.end()
