# -*- coding: utf-8 -*-
"""StatGI Qt 版 · 通用控件

就这几样：
  - Card        半透明卡片
  - SettingRow  一行设置：[图标] 标题+说明 …… [右边控件]
  - Switch      开关（自己画的：胶囊轨道 + 白色圆点）
  - Accordion   折叠区
  - Heading     页面大标题
"""
from PySide6.QtCore import Qt, Signal, QRectF, QSize, QVariantAnimation
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import (QFrame, QLabel, QPushButton, QHBoxLayout,
                               QVBoxLayout, QWidget)

from qt_theme import (RADIUS_CARD, RADIUS_BTN, card_qss, label_qss, title_qss,
                      btn_qss)
import qt_theme as T
from qt_icon import (IconWidget, HoverHelper, has_icon, attach_hover,
                     icon_qicon)


def _find_window(parent):
    """找一个**真正的、可见的顶层窗口**当参照。

    ⚠ 传进来的 parent 不一定还挂在窗口上：比如设置页调 rebuild_ui() 重建
      界面时会先把旧页面 setParent(None)，之后再弹提示 —— 那时
      parent.window() 返回的是它自己，根本不知道主窗口在哪，
      弹窗就只能落在系统默认位置（屏幕左上角）。
    """
    from PySide6.QtWidgets import QApplication

    if parent is not None:
        try:
            w = parent.window()
            if w is not None and w.isVisible():
                return w
        except RuntimeError:
            pass                      # C++ 对象已经没了
    try:
        w = QApplication.activeWindow()
        if w is not None and w.isVisible():
            return w
        for w in QApplication.topLevelWidgets():
            if w.isVisible() and w.isWindow():
                return w
    except Exception:
        pass
    return None


def _center_on_parent(box, win):
    """把 box 摆到 win 的正中间"""
    if box is None or win is None:
        return
    g = win.frameGeometry()
    box.move(g.center().x() - box.width() // 2,
             g.center().y() - box.height() // 2)


def msg_info(parent, title, text, icon=None):
    """弹提示框，**居中显示在主窗口上**。

    QMessageBox 自己会跑到屏幕中间/左上角，得手动摆。两个要点：
    1. 参照物必须是**主窗口**（见 _find_window）
    2. 位置要在 show() **之后**摆 —— Qt 显示对话框时会自己重新定位一次，
       exec() 之前摆好的会被覆盖
    """
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox

    win = _find_window(parent)
    box = QMessageBox(win if win is not None else parent)
    box.setIcon(QMessageBox.Information if icon is None else icon)
    box.setWindowTitle(title)
    box.setText(text)
    box.setStandardButtons(QMessageBox.Ok)
    box.adjustSize()

    place = lambda: _center_on_parent(box, win)
    place()
    box.show()
    QApplication.processEvents()
    place()
    # 再排几次，兜住窗口管理器/系统可能做的二次定位
    for delay in (0, 20, 60, 150):
        QTimer.singleShot(delay, place)
    box.exec()
    return box


def set_btn_icon(button, icon, size=15, role="TEXT", color=None):
    """给按钮加矢量图标（替代以前写在按钮文字里的 emoji）"""
    if has_icon(icon):
        button.setIcon(icon_qicon(icon, size, role=role, color=color))
        button.setIconSize(QSize(size, size))
    return button


def small_button(text, callback=None, alpha=150, kind="normal", icon=None,
                 width=None, height=30):
    """小按钮（折叠区里的操作用）"""
    b = QPushButton(text)
    b.setFixedHeight(height)
    if width:
        b.setFixedWidth(width)
    b.setCursor(Qt.PointingHandCursor)
    b.setStyleSheet(btn_qss(kind, alpha))
    set_btn_icon(b, icon, 14)
    if callback is not None:
        b.clicked.connect(callback)
    return b


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


class IconBox(QWidget):
    """卡片左边那个小图标方块。

    icon 传 Lucide 图标名（如 "trash"）就画矢量图标；传 emoji 就当文字画 ——
    两种都支持，而且鼠标悬停都由外层卡片驱动（见 attach_hover）。
    """

    def __init__(self, icon, parent=None, size=42, role="TEXT", icon_color=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._role = role
        self._bg = QColor(255, 255, 255, 20)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # 0.55 倍：矢量图标边长 ≈ 23px；emoji 字号 ≈ 18px（跟以前一致）
        self.icon_widget = IconWidget(self, name=icon,
                                      size=int(round(size * 0.55)),
                                      role=role, color=icon_color, stroke=2.0)
        lay.addWidget(self.icon_widget, 0, Qt.AlignCenter)

    def set_icon(self, icon):
        if self.icon_widget is not None:
            self.icon_widget.set_name(icon)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(self._bg)
        p.drawRoundedRect(0, 0, self.width(), self.height(), 12, 12)
        p.end()


class SettingRow(Card):
    """一行设置卡片：[图标] 标题 + 说明 …… [右边给的控件]

    这是整个程序里用得最多的一个控件 —— 设置页、启动页全是它。
    """

    def __init__(self, parent=None, icon="", title="", desc="", right=None,
                 alpha=150, height=70, icon_color=None):
        super().__init__(parent, alpha=alpha)
        if height:                       # height=None → 高度跟着内容走
            self.setFixedHeight(height)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(12)

        ic = IconBox(icon, role="TEXT" if icon_color is None else "TEXT",
                     icon_color=icon_color)
        self.icon_box = ic
        self.icon_widget = ic.icon_widget
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

        # 鼠标放到整行上 → 图标弹一下
        attach_hover(self, self.icon_widget)

    def set_text(self, title=None, desc=None):
        """只改文字 —— 不会重建控件"""
        if title is not None:
            self.title_label.setText(title)
        if desc is not None:
            self.desc_label.setText(desc)


ACCORDION_INSET = 12      # 子卡片比主卡片窄多少（左右各缩进）


class SubRow(Card):
    """折叠区里的子卡片：[图标] 标题 + 说明 …… [右边控件]

    跟 SettingRow 是同一个版式，只是小一号（图标方块和行高都小些）。
    """

    def __init__(self, parent=None, icon="", title="", desc="", right=None,
                 alpha=150, height=58, box=32, icon_color=None):
        super().__init__(parent, alpha=alpha)
        self.setFixedHeight(height)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)

        self.icon_box = IconBox(icon, size=box, icon_color=icon_color)
        self.icon_widget = self.icon_box.icon_widget
        lay.addWidget(self.icon_box)

        mid = QVBoxLayout()
        mid.setSpacing(1)
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet(label_qss(T.TEXT, 14, True))
        self.desc_label = QLabel(desc)
        self.desc_label.setStyleSheet(label_qss(T.DIM, 12))
        mid.addWidget(self.title_label)
        mid.addWidget(self.desc_label)
        lay.addLayout(mid, 1)

        self.right = right
        if right is not None:
            lay.addWidget(right)

        attach_hover(self, self.icon_widget)


def _extract_body_items(body_widget):
    """把折叠区的内容拆成「一项一个控件」，好逐项包卡片。

    - 直接放进去的控件：原样取出
    - addLayout 放进去的布局：套一层控件取出来
    - addStretch / addSpacing：**丢掉** —— 子卡片之间不留空隙
    """
    if body_widget is None:
        return []
    lay = body_widget.layout()
    if lay is None:
        return [body_widget]

    items = []
    while lay.count():
        it = lay.takeAt(0)
        w = it.widget()
        if w is not None:
            items.append(w)
            continue
        sub = it.layout()
        if sub is not None:
            holder = QWidget()
            holder.setLayout(sub)
            items.append(holder)
    return items


class Accordion(QWidget):
    """折叠区：点标题原地展开。

    展开后**每一项都是一张子卡片** —— 跟主卡片长得一样，只是左右窄一点；
    子卡片之间、以及第一张子卡片跟主卡片之间都**不留空隙**。
    """

    def __init__(self, parent=None, icon="", title="", desc="", items=None,
                 body_widget=None, alpha=150, on_toggle=None, footer=None,
                 item_alpha=None):
        super().__init__(parent)
        # 兼容旧写法：有人把「内容控件」当成第 5 个位置参数传进来
        # （以前 body_widget 就在那个位置）。自动认出来，
        # 否则会被当成 items 去遍历 → TypeError 崩溃。
        if isinstance(items, QWidget):
            if body_widget is None:
                body_widget = items
            items = None
        self._open = False
        self._on_toggle = on_toggle
        self._alpha = alpha
        ia = alpha if item_alpha is None else item_alpha

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---- 主卡片：只有标题 ----
        self.header = Card(self, alpha=alpha)
        self.v = QVBoxLayout(self.header)
        self.v.setContentsMargins(14, 12, 14, 12)
        self.v.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(12)
        self.ic = IconBox(icon, self.header)
        self.icon_widget = self.ic.icon_widget
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
        outer.addWidget(self.header)

        # ---- 内容区：每一项一张子卡片 ----
        self.body = QWidget(self)
        bv = QVBoxLayout(self.body)
        bv.setContentsMargins(ACCORDION_INSET, 0, ACCORDION_INSET, 0)
        bv.setSpacing(0)                      # 子卡片之间不留空隙
        self.item_cards = []

        # 规范写法：items 里每项是 (图标, 标题, 说明, 右边控件)
        for it in (items or []):
            vals = list(it) + [None] * (4 - len(it))
            ic_name, ti, de, right = vals[0], vals[1], vals[2], vals[3]
            card = SubRow(self.body, icon=ic_name, title=ti, desc=de,
                          right=right, alpha=ia)
            bv.addWidget(card)
            self.item_cards.append(card)

        # 兼容旧写法：直接丢一个控件进来，自动拆成一项一张卡片
        for w in _extract_body_items(body_widget):
            card = Card(self.body, alpha=ia)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(12, 10, 12, 10)
            cl.setSpacing(0)
            cl.addWidget(w)
            bv.addWidget(card)
            self.item_cards.append(card)

        # 页脚提示（不包卡片，直接贴在卡片下面）
        if footer is not None:
            fw = QWidget(self.body)
            fl = QVBoxLayout(fw)
            fl.setContentsMargins(4, 8, 4, 6)
            fl.addWidget(footer)
            bv.addWidget(fw)

        self.body.setVisible(False)
        outer.addWidget(self.body)

        # 点标题那一条就能展开/收起
        for w in (self.header, self.ic, self.title_label, self.desc_label,
                  self.arrow):
            w.setCursor(Qt.PointingHandCursor)
            w.mousePressEvent = self._toggle

        # 鼠标放到主卡片上 → 图标弹一下
        attach_hover(self.header, self.icon_widget)

    def set_alpha(self, alpha, radius=None):
        """（兼容老代码）整块一起改透明度"""
        self._alpha = alpha
        self.header.set_alpha(alpha, radius)
        for c in self.item_cards:
            c.set_alpha(alpha, radius)

    def _toggle(self, _e=None):
        self._open = not self._open
        self.body.setVisible(self._open)
        self.arrow.setText("▾" if self._open else "▸")
        if self._on_toggle:
            self._on_toggle(self._open)


class IconButton(QFrame):
    """带矢量图标的小按钮 —— 鼠标悬停时**图标会弹一下**。

    为什么不用 QPushButton.setIcon：那是一张静态图片，做不了悬停动画。
    这里的底色自己画（跟 btn_qss 的配色一致）。
    """

    clicked = Signal()

    def __init__(self, parent=None, icon="", text="", alpha=150, kind="normal",
                 height=32, icon_size=15, active=False):
        super().__init__(parent)
        self.setFixedHeight(height)
        self.setCursor(Qt.PointingHandCursor)
        self._kind = kind
        self._alpha = alpha
        self._hover = False
        self._active = bool(active)
        self._enabled = True

        layout_margin = (12, 0, 14, 0) if text else (0, 0, 0, 0)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(*layout_margin)
        lay.setSpacing(7)
        self.icon_widget = IconWidget(self, name=icon, size=icon_size,
                                      role=self._icon_role())
        lay.addWidget(self.icon_widget)
        self.label = None
        if text:
            self.label = QLabel(text)
            self.label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            self.label.setStyleSheet(label_qss(self._fg(), 13))
            lay.addWidget(self.label)
        else:
            # 纯图标按钮：做成方的，省横向空间
            self.setFixedSize(height + 6, height)

        self._hh = HoverHelper(self, self._on_hover)

    # ---- 配色（跟 btn_qss 一致，但这里要拿 QColor 自己画）----

    def _fg(self):
        if not self._enabled:
            return T.DIM
        if self._active:
            return T.ACCENT
        if self._kind == "accent":
            return "#08222E"
        return T.TEXT

    def _icon_role(self):
        return "ACCENT" if self._active else "TEXT"

    def _colors(self):
        a = 150 if self._alpha is None else self._alpha

        def al(color, alpha):
            """QColor.setAlpha 只接受 0~255，超了会报警并刷爆 error.log"""
            c = QColor(color)
            c.setAlpha(max(0, min(255, int(alpha))))
            return c

        if not self._enabled:
            return al(T.BTN, 70), al(T.BTN, 70)
        if self._active:
            return al(T.ACCENT, 55), al(T.ACCENT, 85)
        if self._kind == "accent":
            return al(T.ACCENT, max(160, a + 50)), al(T.ACCENT, 255)
        if self._kind == "danger":
            return al(T.DANGER, max(140, a + 40)), al(T.DANGER_HOVER, 230)
        return al(T.BTN, a + 60), al(T.BTN_HOVER, a + 90)

    # ---- 对外 ----

    def set_text(self, text):
        if self.label is not None:
            self.label.setText(text)

    def set_icon(self, icon):
        self.icon_widget.set_name(icon)

    def set_active(self, on):
        self._active = bool(on)
        self.icon_widget.set_color(role=self._icon_role())
        if self.label is not None:
            self.label.setStyleSheet(label_qss(self._fg(), 13))
        self.update()

    def set_enabled(self, on):
        self._enabled = bool(on)
        self.setCursor(Qt.PointingHandCursor if on else Qt.ArrowCursor)
        self.update()

    def _on_hover(self, on):
        self._hover = on
        if self._enabled:
            self.icon_widget.set_hover(on)
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self._enabled:
            self.clicked.emit()
            e.accept()

    def paintEvent(self, e):
        bg, hv = self._colors()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(Qt.NoPen)
        p.setBrush(hv if (self._hover and self._enabled) else bg)
        p.drawRoundedRect(self.rect(), RADIUS_BTN, RADIUS_BTN)
        p.end()


class ButtonRow(QWidget):
    """一排按钮，用来塞进 Accordion 里

    items 每项是 (文字, 回调) 或 (文字, 回调, 图标名)。
    """

    def __init__(self, parent=None, items=(), alpha=150):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.buttons = {}
        for item in items:
            text, cb = item[0], item[1]
            icon = item[2] if len(item) > 2 else None
            b = QPushButton(text)
            b.setFixedHeight(34)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(btn_qss("normal", alpha))
            set_btn_icon(b, icon, 15)
            if cb is not None:
                b.clicked.connect(cb)
            lay.addWidget(b)
            self.buttons[text] = b
        lay.addStretch(1)
