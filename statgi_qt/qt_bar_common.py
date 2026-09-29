# -*- coding: utf-8 -*-
"""悬浮窗编辑器用的两个 label 助手。

从 qt_bar_editor.py 拆出来的（第 4 批，纯搬运）——
因为编辑器和 MaterialPicker **两边都要用 `_lab`**，
放在任何一边都会让另一边反向依赖。

⚠ 这俩函数是**同一个根因**的两个补丁，别把它们的来历弄丢：
   对话框那层 QSS 里有一条 `QLabel { ... }`，Qt 的样式引擎会因此把 QLabel 的
   frameWidth 当成 1、顺手画一圈边框 —— 现象就是「标签文字外面多一个圆角细框」。
   必须显式声明 background/border 才能压掉。"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
import copy
import json
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QCheckBox, QComboBox, QLineEdit,
                               QSlider, QScrollArea, QFrame, QWidget,
                               QStackedWidget, QColorDialog, QMessageBox,
                               QInputDialog, QMenu, QListWidget, QListWidgetItem,
                               QFileDialog)
import qt_theme as T
from qt_widgets import SettingRow, Accordion, small_button, Switch
from qt_window import NavButton
import icons_lib


def _lab(text, size=13, bold=False, color=None):
    """不画底、不画框的 QLabel（本文件统一用它建标签）。

    ⚠ 对话框那层 QSS 里有一条 `QLabel { ... }`，Qt 的样式引擎会因此把
    QLabel 的 frameWidth 当成 1、顺手画一圈边框 —— 实测就是「标签文字
    外面多一个圆角细框」。必须显式声明 background/border 才能压掉。
    （2026-09-23 用像素聚类定位：label 矩形内恰好 108 个强调色像素）
    """
    w = QLabel(text)
    w.setStyleSheet(T.label_qss(color or T.TEXT, size, bold)
                    + "; background: transparent; border: none;")
    return w


def _fix_label_bg(lab):
    """给 label 的样式补上「不画底」。

    同一个根因：QLabel 从 QSS 级联继承了背景色，Qt 就会把它的底/框画出来。
    NavButton 的 label 由主界面控件自己设样式，我们管不着它，
    只能在拿到之后补一刀。

    ⚠ `NavButton.set_active()` 每次都会重设 label 的样式，所以切换页面后
    必须再补一次 —— 这就是为什么 `_nav()` 里也要调。
    """
    ss = lab.styleSheet()
    if "background" not in ss:
        lab.setStyleSheet(ss + "; background: transparent; border: none;")
