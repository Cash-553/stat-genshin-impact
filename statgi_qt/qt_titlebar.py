# -*- coding: utf-8 -*-
"""标题栏：图标 + 标题 / 副标题 + 最小化 / 关闭按钮。

从 qt_window.py 拆出来的（第 3 批，纯搬运）。"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QHBoxLayout
from qt_theme import HEADER, RADIUS_WINDOW, label_qss, rgba
import qt_theme as T
from qt_icon import IconWidget


# ============================================================
#  标题条
# ============================================================
class TitleBar(QFrame):
    def __init__(self, win, title="StatGI", subtitle=""):
        super().__init__(win)
        self.win = win
        self._drag = None
        self.setFixedHeight(46)
        self.setStyleSheet(
            f"QFrame {{ background: {rgba(HEADER, 190)};"
            f" border-top-left-radius: {RADIUS_WINDOW}px;"
            f" border-top-right-radius: {RADIUS_WINDOW}px; }}")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 8, 0)
        lay.setSpacing(0)

        # 应用图标用 emoji（叶子），其余图标仍是矢量图标
        ico = IconWidget(self, name="🍃", size=20, role="ACCENT")
        lay.addWidget(ico)
        lay.addSpacing(8)
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet(label_qss(T.TEXT, 14, True))
        lay.addWidget(self.title_label)
        lay.addSpacing(14)
        self.sub_label = QLabel(subtitle)
        self.sub_label.setStyleSheet(label_qss(T.DIM, 12))
        lay.addWidget(self.sub_label)
        lay.addStretch(1)

        # 标题栏这两个按钮用文字符号，不用矢量图标 —— 试过图标，显示效果不好
        for text, cb, danger in (("—", self.win.showMinimized, False),
                                 ("✕", self.win.close, True)):
            b = QPushButton(text)
            b.setFixedSize(42, 30)
            b.setCursor(Qt.PointingHandCursor)
            hover = "#C0392B" if danger else "#3A3A3A"
            b.setStyleSheet(
                f"QPushButton {{ background:transparent; color:{T.TEXT}; border:none;"
                f" border-radius:6px; font-size:13px; }}"
                f"QPushButton:hover {{ background:{hover}; }}")
            b.clicked.connect(cb)
            lay.addWidget(b)

    # 按住标题条拖动窗口（子控件不会把鼠标事件冒泡给主窗口，所以写在这里）
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.win.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self.win.move(e.globalPosition().toPoint() - self._drag)
            e.accept()

    def mouseReleaseEvent(self, e):
        self._drag = None
