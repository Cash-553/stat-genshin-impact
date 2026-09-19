# -*- coding: utf-8 -*-
"""StatGI Qt 版 · 收益统计条（直播间小窗口）

Tk 版那个统计条是靠"把窗口整体设一个 alpha"来做半透明的，
Qt 版用的是**真·逐像素透明**（WA_TranslucentBackground）——
格子背景半透明、圆角、边缘干净，OBS 里窗口捕获出来不会有黑边。

格子图标读 settings["stat_bar"]["slot1/2/3"]，跟 Tk 版共用同一份设置。
"""
import os

from PySide6.QtCore import Qt, QPoint, QTimer
from PySide6.QtGui import QPainter, QPainterPath, QPixmap, QColor, QFont
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel

import paths
import qt_theme as T

ICONS_DIR = paths.icons_dir()


def fmt_num(n):
    return f"{n:,}"


class Slot(QWidget):
    """一个格子：上面图标，下面数量"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(96, 96)
        self._icon = None
        self._icon_key = None

        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(0, 8, 0, 8)
        self.v.setSpacing(2)

        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setFixedHeight(52)
        self.count_label = QLabel("0")
        self.count_label.setAlignment(Qt.AlignCenter)
        self.count_label.setStyleSheet(
            f"color:{T.TEXT}; font-family:'Microsoft YaHei UI'; font-size:17px;"
            " font-weight:700; background: transparent;")
        self.v.addWidget(self.icon_label)
        self.v.addWidget(self.count_label)

    def set_icon_file(self, path):
        """只在图标变了的时候才重新加载图片"""
        if path == self._icon_key:
            return
        self._icon_key = path
        if path and os.path.exists(path):
            pm = QPixmap(path)
            if not pm.isNull():
                self._icon = pm.scaled(46, 46, Qt.KeepAspectRatio,
                                       Qt.SmoothTransformation)
                self.icon_label.setPixmap(self._icon)
                return
        self.icon_label.setPixmap(QPixmap())
        self.icon_label.setText("◆")
        self.icon_label.setStyleSheet(f"color:{T.ACCENT}; font-size:22px;")

    def set_count(self, text):
        """只有文字真的变了才写（写一次会触发一次重绘）"""
        if self.count_label.text() != text:
            self.count_label.setText(text)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        path = QPainterPath()
        path.addRoundedRect(1, 1, self.width() - 2, self.height() - 2, 12, 12)
        p.fillPath(path, QColor(20, 20, 24, 150))     # 半透明格子底
        p.end()


class StatBarWindow(QWidget):
    """收益统计条窗口：可拖动、可置顶、可调透明度、格子可隐藏"""

    def __init__(self, state, on_closed=None):
        super().__init__()
        self.state = state
        self._on_closed = on_closed
        self._drag = None
        self._last = None

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                            | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowTitle("收益统计条")

        self.slots = {}
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)
        for key in ("slot1", "slot2", "slot3"):
            s = Slot(self)
            self.slots[key] = s
            lay.addWidget(s)

        self.apply_appearance()

        # 自己一个 500ms 定时器：只在这个小窗口里刷，跟主界面互不影响
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(500)
        self.refresh()

    # ---------- 外观 ----------
    def apply_appearance(self):
        bar = self.state.settings.get("stat_bar") or {}
        for key, s in self.slots.items():
            s.setVisible(bool(bar.get("show_" + key, True)))
            fname = bar.get(key)
            s.set_icon_file(ICONS_DIR / fname if fname else None)
        try:
            op = float(bar.get("opacity", 1.0))
        except Exception:
            op = 1.0
        self.setWindowOpacity(max(0.2, min(1.0, op)))
        self.setWindowFlag(Qt.WindowStaysOnTopHint,
                           bool(bar.get("always_on_top", True)))
        self.show()

    # ---------- 数据 ----------
    def refresh(self):
        snap = self.state.snapshot()
        mats = sum(snap["materials"].values())
        vals = {"slot1": fmt_num(snap["mora"]),
                "slot2": str(mats),
                "slot3": str(snap["artifact"])}
        if vals == self._last:          # 数据没变 -> 一个字都不动
            return
        self._last = vals
        for key, s in self.slots.items():
            s.set_count(vals[key])

    # ---------- 拖动 ----------
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)
            e.accept()

    def mouseReleaseEvent(self, e):
        self._drag = None

    def closeEvent(self, e):
        try:
            self._timer.stop()
        except Exception:
            pass
        if self._on_closed:
            self._on_closed()
        super().closeEvent(e)
