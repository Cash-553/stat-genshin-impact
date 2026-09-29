# -*- coding: utf-8 -*-
"""侧栏：导航按钮 + 公告入口 + 左下角版本号 / 「检测到新版本」闪烁。

从 qt_window.py 拆出来的（第 3 批，纯搬运）。"""

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
from qt_bg import _blur
from qt_navbtn import NavButton


# 左下角「检测到新版本」闪烁：一帧 33ms（约 30fps），一个来回 1200ms
_BLINK_MS = 33
_BLINK_PERIOD_MS = 1200.0
# ⚠ 不要用 T.DANGER —— 那是「背景色的浅色版」（深灰），闪出来是白↔深灰不是白↔红。
#   跟侧栏公告红点用同一个红。
_BLINK_RED = "#E06C5A"


# ============================================================
#  左侧栏（磨砂玻璃）
# ============================================================
class Sidebar(QFrame):
    def __init__(self, win, items, on_select):
        super().__init__(win)
        self.win = win
        self.setFixedWidth(190)
        self._blur = None
        self._glass = bool((win.state.settings or {}).get("sidebar_glass", True))
        self._items = items
        self._on_select = on_select

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 14, 10, 14)
        lay.setSpacing(4)

        self.buttons = []
        self.nav_dots = {}          # 导航名 -> 小红点（检测到新版本时挂在「设置」上）
        for i, (icon, name) in enumerate(items):
            b = NavButton(self, icon, name)
            b.clicked.connect(lambda idx=i: self._on_select(idx))
            lay.addWidget(b)
            self.buttons.append(b)
            self.nav_dots[name] = RedDot(b)

        lay.addStretch(1)

        # ---- 公告（放在导航和版本号之间，做一个独立入口）----
        # 它不是"页面"，点一下是弹窗 —— 所以不参与 set_active 的高亮
        self.notice_btn = NavButton(self, "megaphone", "公告")
        self.notice_btn.clicked.connect(self._on_notice_click)
        lay.addWidget(self.notice_btn)

        # 未读小红点：浮在按钮右上角（做成按钮的子控件，跟着按钮走）
        self.notice_dot = QLabel("●", self.notice_btn)
        self.notice_dot.setStyleSheet(
            "color:#E06C5A; font-size:13px; background:transparent;")
        self.notice_dot.setFixedSize(16, 16)
        self.notice_dot.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.notice_dot.hide()

        # 左下角版本号。检测到新版本时会变成「检测到新版本」并闪红光
        # 从 qt_pages.VERSION 取，别写死 —— 以前写死 V0.9，改版本号会漏掉这里
        self.ver_label = QLabel("V" + _VERSION)
        self.ver_label.setStyleSheet(label_qss(T.DIM, 12))
        self.ver_label.setAlignment(Qt.AlignCenter)
        self.ver_label.setCursor(Qt.PointingHandCursor)
        self.ver_label.mousePressEvent = self._on_ver_click
        lay.addWidget(self.ver_label)

        self._upd_on = False
        self._upd_ver = ""
        self._upd_t = 0.0
        self._upd_timer = QTimer(self)
        self._upd_timer.setInterval(_BLINK_MS)
        self._upd_timer.timeout.connect(self._blink_tick)

        self.set_active(0)

    # ---- 检测到新版本：闪烁提示 ----

    def set_update_available(self, on, version=""):
        """检测到新版本 → 左下角换成「检测到新版本」并一直闪红光"""
        self._upd_on = bool(on)
        self._upd_ver = str(version or "")
        # 侧栏「设置」那一项也挂个红点（更新是在 设置→其它 里点的）
        dot = getattr(self, "nav_dots", {}).get("设置")
        if dot is not None:
            dot.set_on(self._upd_on)
        if self._upd_on:
            self.ver_label.setText("检测到新版本")
            self.ver_label.setToolTip(
                (f"发现新版本 {self._upd_ver}" if self._upd_ver else "发现新版本")
                + "，点这里去更新")
            self._upd_t = 0.0
            self._blink_tick()
            self._upd_timer.start()
        else:
            self._upd_timer.stop()
            self.ver_label.setText("V" + _VERSION)
            self.ver_label.setStyleSheet(label_qss(T.DIM, 12))
            self.ver_label.setToolTip("")

    def _blink_tick(self):
        """白 → 红 → 白 平滑来回，一个来回约 1.2 秒（不会太快晃眼）"""
        self._upd_t += _BLINK_MS / _BLINK_PERIOD_MS
        k = 0.5 - 0.5 * math.cos(2 * math.pi * self._upd_t)     # 0~1 平滑
        white, red = QColor("#FFFFFF"), QColor(_BLINK_RED)
        cur = QColor(int(white.red() + (red.red() - white.red()) * k),
                     int(white.green() + (red.green() - white.green()) * k),
                     int(white.blue() + (red.blue() - white.blue()) * k))
        self.ver_label.setStyleSheet(
            f"color:{cur.name()}; font-size:12px; font-weight:700;")

    def _on_ver_click(self, _e=None):
        if self._upd_on:
            fn = getattr(self.win, "show_update_settings", None)
            if callable(fn):
                fn()

    def _on_notice_click(self):
        fn = getattr(self.win, "show_notice_page", None)
        if callable(fn):
            fn()

    def set_notice_unread(self, unread):
        """有没有未读公告 —— 有就在公告那一项右上角挂个红点"""
        self.notice_dot.setVisible(bool(unread))
        if unread:
            self._place_dot()
            self.notice_dot.raise_()

    def _place_dot(self):
        """把红点摆在按钮右上角（按钮大小定了之后才准）"""
        b = self.notice_btn
        self.notice_dot.move(max(0, b.width() - 20), 4)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_dot()

    def showEvent(self, e):
        super().showEvent(e)
        self._place_dot()

    def set_active(self, idx):
        for i, b in enumerate(self.buttons):
            b.set_active(i == idx)

    def set_glass(self, on):
        """毛玻璃开关：关掉就不模糊背景图，只压暗"""
        self._glass = bool(on)
        self.refresh_bg()

    def refresh_bg(self):
        self._blur = None
        self.update()

    def paintEvent(self, e):
        # 侧栏 = 背景图上**对应位置**那一块 +（可选）模糊 + 压暗
        #
        # 关键：要从窗口坐标里取自己那一块，不能拿 self.rect()（那是自己的
        # 局部坐标，永远从 0,0 开始）—— 否则背景图会整体上移一个标题条的高度，
        # 看起来就是「侧栏的图错位了」。
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)

        # 左下角跟着窗口一起圆角，否则整个窗口的左下角会被切成直角
        r = self.rect()
        path = QPainterPath()
        path.moveTo(r.left(), r.top())
        path.lineTo(r.right() + 1, r.top())
        path.lineTo(r.right() + 1, r.bottom() - RADIUS_WINDOW + 1)
        path.quadTo(r.right() + 1, r.bottom() + 1,
                    r.right() - RADIUS_WINDOW + 1, r.bottom() + 1)
        path.lineTo(r.left() + RADIUS_WINDOW, r.bottom() + 1)
        path.quadTo(r.left(), r.bottom() + 1, r.left(), r.bottom() - RADIUS_WINDOW + 1)
        path.closeSubpath()
        p.setClipPath(path)

        bg = self.win.background()
        if bg.isNull():
            p.fillRect(r, QColor(T.SIDEBAR))
        else:
            if self._blur is None:
                # 自己在窗口里的位置（含标题条高度）
                top_left = self.mapTo(self.win, QPoint(0, 0))
                crop = bg.copy(QRect(top_left.x(), top_left.y(),
                                     self.width(), self.height()))
                self._blur = _blur(crop, 12) if getattr(self, "_glass", True) else crop
            if self._blur is not None:
                p.drawPixmap(0, 0, self._blur)
            p.fillRect(r, QColor(12, 12, 14, 150))
        p.end()
