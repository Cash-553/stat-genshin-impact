# -*- coding: utf-8 -*-
"""StatGI Qt 版 · 通用控件

就这几样：
  - Card        半透明卡片
  - SettingRow  一行设置：[图标] 标题+说明 …… [右边控件]
  - Switch      开关（自己画的：胶囊轨道 + 白色圆点）
  - Accordion   折叠区
  - Heading     页面大标题
"""
from PySide6.QtCore import Qt, Signal, QRectF, QVariantAnimation
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import (QFrame, QLabel, QPushButton, QHBoxLayout,
                               QVBoxLayout, QWidget)

from qt_theme import (RADIUS_CARD, card_qss, label_qss, title_qss, btn_qss)
import qt_theme as T


def heading(text, parent=None):
    lb = QLabel(text, parent)
    lb.setStyleSheet(title_qss())
    return lb


def level_name(levels, value, default_name):
    """数值 -> 档位名字。

    levels 形如 [("性能", 100), ("标准", 150), ...]。
    找不到完全相等的就取**最接近**的那一档（老设置里可能存着已经不在
    表里的值），实在不行用默认名字。
    """
    try:
        v = float(value)
    except Exception:
        return default_name
    best, best_d = None, None
    for name, val in levels:
        d = abs(float(val) - v)
        if best_d is None or d < best_d:
            best, best_d = name, d
    return best or default_name


def level_value(levels, name, default_value):
    """档位名字 -> 数值"""
    for n, v in levels:
        if n == name:
            return v
    return default_value


class Card(QFrame):
    """半透明卡片。alpha 是 0~255 的透明度。"""

    def __init__(self, parent=None, alpha=150, radius=RADIUS_CARD):
        super().__init__(parent)
        self.setObjectName("card")
        self.set_alpha(alpha, radius)
        self._alpha = alpha
        self._radius = radius

    def set_alpha(self, alpha, radius=None):
        self._alpha = alpha
        if radius is not None:
            self._radius = radius
        self.setStyleSheet(card_qss(self._alpha, self._radius))


class Switch(QWidget):
    """开关：胶囊轨道 + 一个白色圆点；开=强调色，关=灰色

    为什么不用 QCheckBox 穿皮肤？因为 QSS 只能改 indicator 的底色，
    **画不出那个圆点** —— 看起来就是一个色块，分不清开还是关。
    所以这里自己画（顺便加了个 120ms 的滑动动画）。
    """

    toggled = Signal(bool)

    def __init__(self, parent=None, checked=False, command=None):
        super().__init__(parent)
        self.setFixedSize(46, 24)
        self.setCursor(Qt.PointingHandCursor)
        self._on = bool(checked)
        self._t = 1.0 if self._on else 0.0        # 动画进度：0=关 1=开

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(120)
        self._anim.valueChanged.connect(self._on_anim)

        if command is not None:
            self.toggled.connect(command)

    # ---- 跟 QCheckBox 一样的接口，方便直接替换 ----
    def isChecked(self):
        return self._on

    def setChecked(self, v):
        v = bool(v)
        if v == self._on:
            return
        self._on = v
        self._anim.stop()
        self._anim.setStartValue(self._t)
        self._anim.setEndValue(1.0 if v else 0.0)
        self._anim.start()
        self.toggled.emit(v)

    def toggle(self):
        self.setChecked(not self._on)

    def _on_anim(self, val):
        self._t = float(val)
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.toggle()
            e.accept()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()

        # 轨道：灰 -> 强调色（颜色现取，所以换强调色立刻生效）
        off = QColor(T.SWITCH_OFF)
        on = QColor(T.ACCENT)
        r = int(off.red() + (on.red() - off.red()) * self._t)
        g = int(off.green() + (on.green() - off.green()) * self._t)
        b = int(off.blue() + (on.blue() - off.blue()) * self._t)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(r, g, b))
        p.drawRoundedRect(0, 0, w, h, h / 2, h / 2)

        # 白色圆点
        d = h - 6
        x = 3 + self._t * (w - d - 6)
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QRectF(x, 3, d, d))
        p.end()


class IconBox(QLabel):
    """卡片左边那个小图标方块"""

    def __init__(self, icon, parent=None, size=42):
        super().__init__(icon, parent)
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(
            f"background: rgba(255,255,255,20); border-radius:12px; font-size:18px;")


class SettingRow(Card):
    """一行设置卡片：[图标] 标题 + 说明 …… [右边给的控件]

    这是整个程序里用得最多的一个控件 —— 设置页、启动页全是它。
    """

    def __init__(self, parent=None, icon="", title="", desc="", right=None,
                 alpha=150, height=70, icon_color=None):
        super().__init__(parent, alpha=alpha)
        self.setFixedHeight(height)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(12)

        ic = IconBox(icon)
        if icon_color:
            ic.setStyleSheet("background: rgba(255,255,255,20); border-radius:12px;"
                             f" font-size:18px; color:{icon_color};")
        lay.addWidget(ic)

        mid = QVBoxLayout()
        mid.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet(label_qss(T.TEXT, 15, True))
        self.desc_label = QLabel(desc)
        self.desc_label.setStyleSheet(label_qss(T.DIM, 12))
        mid.addWidget(self.title_label)
        mid.addWidget(self.desc_label)
        lay.addLayout(mid, 1)

        self.right = right
        if right is not None:
            lay.addWidget(right)

    def set_text(self, title=None, desc=None):
        """只改文字 —— 不会重建控件"""
        if title is not None:
            self.title_label.setText(title)
        if desc is not None:
            self.desc_label.setText(desc)


class Accordion(Card):
    """折叠区：点标题原地展开，带过渡动画

    跟 Tk 版那个 Accordion 长得一样、行为一样，但代码只有它三分之一。
    """

    def __init__(self, parent=None, icon="", title="", desc="",
                 body_widget=None, alpha=150, on_toggle=None):
        super().__init__(parent, alpha=alpha)
        self._open = False
        self._on_toggle = on_toggle

        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(14, 12, 14, 12)
        self.v.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(12)
        self.ic = IconBox(icon)
        head.addWidget(self.ic)
        mid = QVBoxLayout()
        mid.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet(label_qss(T.TEXT, 15, True))
        self.desc_label = QLabel(desc)
        self.desc_label.setStyleSheet(label_qss(T.DIM, 12))
        mid.addWidget(self.title_label)
        mid.addWidget(self.desc_label)
        head.addLayout(mid, 1)
        self.arrow = QLabel("▸")
        self.arrow.setStyleSheet(label_qss(T.DIM, 15))
        head.addWidget(self.arrow)
        self.v.addLayout(head)

        # 内容区（调用方传进来的控件）
        self.body = body_widget if body_widget is not None else QWidget()
        self.body.setVisible(False)
        self.v.addWidget(self.body)

        for w in (self, self.ic, self.title_label, self.desc_label, self.arrow):
            w.setCursor(Qt.PointingHandCursor)
            w.mousePressEvent = self._toggle

    def _toggle(self, _e=None):
        self._open = not self._open
        self.body.setVisible(self._open)
        self.arrow.setText("▾" if self._open else "▸")
        if self._on_toggle:
            self._on_toggle(self._open)


class ButtonRow(QWidget):
    """一排按钮，用来塞进 Accordion 里"""

    def __init__(self, parent=None, items=(), alpha=150):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.buttons = {}
        for text, cb in items:
            b = QPushButton(text)
            b.setFixedHeight(34)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(btn_qss("normal", alpha))
            if cb is not None:
                b.clicked.connect(cb)
            lay.addWidget(b)
            self.buttons[text] = b
        lay.addStretch(1)
