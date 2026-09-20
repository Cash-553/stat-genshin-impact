# -*- coding: utf-8 -*-
"""界面图标 —— Lucide 描边图标 + 悬停时的弹性缩放。

图标本身不变，鼠标放到卡片/设置行上时只是「弹一下」（放大 1.18 倍），
移开弹回。动画用阻尼谐振子（半隐式欧拉，h = 1/240），参数取自
morphicons 的 snappy 预设（k=420, c=30）。

图标轮廓点在 qt_icon_data.py 里（离线用 morphicons 的采样器生成）。
颜色按「角色名」延迟读取 qt_theme，所以换主题色能立刻生效。
"""

import math

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

import qt_theme as T

try:
    from qt_icon_data import ICONS
except ImportError:      # 以包的形式导入时
    from .qt_icon_data import ICONS

VIEW = 24.0
FRAME_MS = 16            # 约 60 fps
DEFAULT_SCALE = 1.18     # 悬停放大倍数（纯缩放，不旋转）


def has_icon(name):
    """这个名字是不是一个内置图标（不是的话当普通文字处理）"""
    return isinstance(name, str) and name in ICONS


def available():
    return sorted(ICONS)


def resolve_color(color=None, role="TEXT"):
    """颜色：给了具体颜色就用它，否则按角色名现读 qt_theme（换主题立刻生效）"""
    if color is not None:
        return QColor(color)
    return QColor(getattr(T, role, T.TEXT))


def draw_subs(p, subs, box, base, scale=1.0, angle=0.0, color="#FFFFFF",
              stroke=2.0):
    """把图标画在边长 box 的方框正中央。

    base 是图标的**自然尺寸**，scale 是当前缩放倍数。两者分开是有意的：
    控件会留出 scale 的余量（box > base），放大时才不会被自己的边界裁掉。
    """
    if not subs or box <= 0 or base <= 0:
        return
    k = base / VIEW
    p.save()
    p.translate(box / 2.0, box / 2.0)
    if angle:
        p.rotate(angle)
    p.scale(scale * k, scale * k)
    p.translate(-VIEW / 2.0, -VIEW / 2.0)

    pen = QPen(color if isinstance(color, QColor) else QColor(color))
    pen.setWidthF(max(1.0, stroke * k))
    pen.setCosmetic(True)          # 线宽不跟着缩放变粗
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)

    for closed, flat in subs:
        poly = QPolygonF([QPointF(flat[i] / 100.0, flat[i + 1] / 100.0)
                          for i in range(0, len(flat), 2)])
        if closed:
            p.drawPolygon(poly)
        else:
            p.drawPolyline(poly)
    p.restore()


def icon_pixmap(name, px=16, role="TEXT", color=None, stroke=2.0):
    """按 px 个**真实像素**渲染一张图标图（不做 DPR 处理，交给调用方）"""
    from PySide6.QtGui import QPixmap

    px = max(1, int(px))
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    if not has_icon(name):
        return pm
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    draw_subs(p, ICONS[name], px, px, 1.0, 0.0, resolve_color(color, role),
              stroke)
    p.end()
    return pm


def icon_qicon(name, size=16, role="TEXT", color=None, stroke=2.0,
               scales=(1, 2, 3)):
    """给 QPushButton.setIcon 用的图标。

    注册 1×/2×/3× 三个尺寸，让 Qt 按屏幕缩放自己挑最合适的那张 ——
    高 DPI 下也是锐利的。**不能**用 setDevicePixelRatio：QIcon 处理不了，
    会把大图当成大尺寸塞进小图标位，结果是只显示左上角一块。
    """
    from PySide6.QtGui import QIcon

    ic = QIcon()
    for s in scales:
        ic.addPixmap(icon_pixmap(name, size * s, role, color, stroke))
    return ic


class Spring:
    """阻尼谐振子：ẍ = k·(target − x) − c·ẋ"""

    PRESETS = {
        "smooth": (170.0, 26.0),   # 临界阻尼，不回弹
        "snappy": (420.0, 30.0),   # 快，轻微过冲（默认）
        "bouncy": (300.0, 14.0),   # 俏皮，回弹明显
    }

    def __init__(self, preset="snappy", value=0.0):
        self.k, self.c = self.PRESETS.get(preset, self.PRESETS["snappy"])
        self.x = float(value)
        self.v = 0.0
        self.target = float(value)

    def to(self, target):
        self.target = float(target)

    def step(self, dt):
        h = 1.0 / 240.0
        steps = max(1, min(int(dt / h) + 1, 32))
        k, c = self.k, self.c
        for _ in range(steps):
            self.v += (k * (self.target - self.x) - c * self.v) * h
            self.x += self.v * h
        return self.x

    def settled(self):
        return abs(self.target - self.x) < 0.001 and abs(self.v) < 0.02


class IconWidget(QWidget):
    """一个图标。悬停时弹性放大，移开弹回。

    传 Lucide 名字（如 "trash"）就画矢量图标；传别的（emoji）就当文字画，
    **两种都能悬停弹跳**。

    默认对鼠标透明 —— 由外层的卡片 / 设置行驱动 `set_hover()`，
    这样鼠标放在整张卡片上就能触发。
    """

    def __init__(self, parent=None, name=None, size=18, role="TEXT",
                 color=None, stroke=2.0, preset="snappy",
                 scale_to=DEFAULT_SCALE, rotate_to=0.0,
                 mouse_transparent=True):
        super().__init__(parent)
        self._name = name
        self._role = role
        self._color = color
        self._stroke = float(stroke)
        self._scale_to = float(scale_to)
        self._rotate_to = float(rotate_to)
        self._subs = ICONS.get(name) if has_icon(name) else None
        # 不是矢量图标名 → 当文字（emoji）画
        self._text = None if self._subs else (name or "")
        self._font_px = max(8, int(round(size * 0.78)))
        self._spring = Spring(preset, 0.0)
        self._hover = False

        self._base = float(size)
        # 控件要留出「放大后的余量」，否则图标一放大就被自己的边界裁掉。
        # 再加 2px：描边本身有宽度，会往外扩一点点。
        growth = max(1.0, self._scale_to)
        box = int(math.ceil(size * growth)) + 2
        self.setFixedSize(box, box)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        if mouse_transparent:
            self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._tick)

    # ---- 对外接口 ----

    def set_color(self, color=None, role=None):
        if role is not None:
            self._role = role
            self._color = None
        if color is not None:
            self._color = color
        self.update()

    def set_name(self, name):
        self._name = name
        self._subs = ICONS.get(name) if has_icon(name) else None
        self._text = None if self._subs else (name or "")
        self._spring.x = self._spring.target = 0.0
        self._spring.v = 0.0
        self.update()

    def set_hover(self, on):
        on = bool(on)
        if on == self._hover:
            return
        self._hover = on
        if not self._subs and not self._text:
            return
        self._spring.to(1.0 if on else 0.0)
        if not self._timer.isActive():
            self._timer.start()

    def hover_progress(self):
        return self._spring.x

    def _current_color(self):
        return resolve_color(self._color, self._role)

    # ---- 也能自己响应鼠标（mouse_transparent=False 时）----

    def enterEvent(self, event):
        self.set_hover(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.set_hover(False)
        super().leaveEvent(event)

    # ---- 动画 ----

    def _tick(self):
        self._spring.step(FRAME_MS / 1000.0)
        if self._spring.settled():
            self._spring.x = self._spring.target
            self._spring.v = 0.0
            self._timer.stop()
        self.update()

    def paintEvent(self, event):
        if not self._subs and not self._text:
            return
        box = min(self.width(), self.height())
        if box <= 0:
            return
        t = self._spring.x
        scale = 1.0 + (self._scale_to - 1.0) * t
        angle = self._rotate_to * t

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)

        if self._subs:
            draw_subs(p, self._subs, box, self._base, scale, angle,
                      self._current_color(), self._stroke)
        else:
            p.translate(box / 2.0, box / 2.0)
            if angle:
                p.rotate(angle)
            p.scale(scale, scale)
            f = QFont(p.font())
            f.setPixelSize(self._font_px)
            p.setFont(f)
            p.setPen(self._current_color())
            p.drawText(QRectF(-box / 2.0, -box / 2.0, box, box),
                       Qt.AlignCenter, self._text)
        p.end()


class HoverHelper(QObject):
    """让整个控件（含子控件）在鼠标进出时回调 callback(bool)。

    为什么不能只用 enterEvent/leaveEvent：鼠标从卡片移到卡片里的子控件上时，
    Qt 会给卡片发一个 Leave —— 用「光标是否还在自己矩形内」兜底才对。
    """

    def __init__(self, widget, callback):
        super().__init__(widget)
        self._w = widget
        self._cb = callback
        self._on = False
        widget.setMouseTracking(True)
        widget.installEventFilter(self)
        self._timer = QTimer(widget)
        self._timer.setInterval(90)
        self._timer.timeout.connect(self._poll)
        self.refresh()

    def refresh(self):
        """控件树变了（新加了子控件）之后调一下"""
        for child in self._w.findChildren(QWidget):
            child.setMouseTracking(True)
            child.installEventFilter(self)

    def is_hovered(self):
        return self._on

    def eventFilter(self, obj, event):
        t = event.type()
        if t in (QEvent.Enter, QEvent.HoverEnter):
            self._set(True)
            if not self._timer.isActive():
                self._timer.start()
        elif t in (QEvent.Leave, QEvent.HoverLeave):
            self._poll()
        return False

    def _poll(self):
        try:
            pos = self._w.mapFromGlobal(QCursor.pos())
        except Exception:
            return
        inside = self._w.rect().contains(pos)
        self._set(inside)
        if not inside:
            self._timer.stop()

    def _set(self, on):
        if on == self._on:
            return
        self._on = on
        self._cb(on)


def attach_hover(widget, *icons):
    """给一个控件挂上悬停检测，鼠标进出时驱动这些图标弹性缩放。

    用法：attach_hover(row, row.icon_widget)
    """
    targets = [w for w in icons if w is not None]

    def _on(on):
        for w in targets:
            w.set_hover(on)

    widget._hover_helper = HoverHelper(widget, _on)
    return widget._hover_helper
