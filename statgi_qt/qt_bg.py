# -*- coding: utf-8 -*-
"""背景图工具：铺底 / 便宜模糊 / 从设置里找背景图。

从 qt_window.py 拆出来的（第 3 批，纯搬运）。

⚠ `_blur` 这个"缩小再放大"的做法就是侧栏磨砂 —— 不是真的高斯模糊，
   但便宜得多，肉眼看不出差别。"""

import os
import math
from PySide6.QtCore import Qt, QRectF, QRect, QPoint, QTimer, Signal
from PySide6.QtGui import QPainter, QPainterPath, QPixmap, QColor, QIcon
from PySide6.QtWidgets import (QWidget, QFrame, QLabel, QPushButton, QVBoxLayout,
                               QHBoxLayout, QStackedWidget, QMessageBox)
import config_manager
import paths
from qt_pages import NOTICE_PAGE_INDEX, VERSION as _VERSION
from qt_theme import (HEADER, RADIUS_WINDOW, panel_alpha, label_qss, rgba,
                      btn_qss)
import qt_theme as T
from qt_icon import IconWidget, HoverHelper, attach_hover
from qt_widgets import RedDot


# ---------- 背景图工具 ----------
def _cover(pm, w, h):
    """把图裁成铺满 w×h（居中裁剪）= CSS 的 cover"""
    if w <= 0 or h <= 0 or pm.isNull():
        return pm
    s = pm.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    return s.copy((s.width() - w) // 2, (s.height() - h) // 2, w, h)


def _blur(pm, factor=10):
    """便宜模糊：缩小再放大。够用，而且不慢。"""
    if pm.isNull():
        return pm
    w, h = max(1, pm.width()), max(1, pm.height())
    small = pm.scaled(max(1, w // factor), max(1, h // factor),
                      Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    return small.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


def load_background(settings):
    """背景图：设置了 bg_image 就用图；**没设置就返回空 = 走纯色背景**

    （以前没设图时会自己画一张渐变图，现在不要了 —— 直接用主题的背景色。）
    """
    p = settings.get("bg_image")
    if p and os.path.exists(p):
        pm = QPixmap(p)
        if not pm.isNull():
            return pm
    return QPixmap()          # 空 = 纯色背景
