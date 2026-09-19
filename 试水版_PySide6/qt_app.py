# -*- coding: utf-8 -*-
"""
StatGI 试水版（PySide6 / Qt）

用来看：如果界面换成 Qt，会长什么样、拖影还在不在、打包多大。

重点对比三件事：
  1) 半透明玻璃背景 —— Tk 里要 800 多行切片贴图，这里就是一个 rgba() 背景色
  2) 滚动有没有拖影 —— 「滚动测试」页有 300 行高饱和色块 + 一键自动滚动
  3) 那些控件是否免费 —— 下拉框 / 开关 / 滑块 / 输入框 / 折叠区，全是现成的

运行：python qt_app.py
（没装 PySide6 的话：pip install PySide6）
"""
import os
import sys

# ---------------- 没装 PySide6 时给个友好提示 ----------------
try:
    from PySide6.QtCore import Qt, QRectF, QTimer
    from PySide6.QtGui import QPainter, QPainterPath, QPixmap, QColor, QLinearGradient
    from PySide6.QtWidgets import (QApplication, QWidget, QFrame, QLabel, QPushButton,
                                   QVBoxLayout, QHBoxLayout, QScrollArea, QComboBox,
                                   QLineEdit, QSlider, QStackedWidget, QSizeGrip,
                                   QCheckBox)
except ImportError:
    print("=" * 56)
    print("  还差一个库：PySide6")
    print("")
    print("  在命令行里跑这一句装一下（大约 100MB，要联网）：")
    print("      pip install PySide6")
    print("")
    print("  装完再运行本文件即可。")
    print("=" * 56)
    sys.exit(1)


HERE = os.path.dirname(os.path.abspath(__file__))
BG_IMAGE = os.path.join(HERE, "bg.jpg")      # 放一张背景图就叫这个名字

# ---- 配色（跟主程序一致）----
BG = "#1C1C1C"
HEADER = "#1F1F1F"
SIDEBAR = "#1A1A1A"
CARD_RGB = (36, 36, 36)
ACCENT = "#4CC2FF"
ACCENT_DARK = "#2E9BD6"
TEXT = "#E8E8E8"
DIM = "#9A9A9A"
BTN = "#2E2E2E"
BTN_HOVER = "#3A3A3A"
DANGER = "#C0392B"

FONT = "Microsoft YaHei UI"

# 卡片透明度（0~255）：这就是主程序里那个「卡片透明度」滑块
CARD_ALPHA = 150


def make_default_bg(w=1600, h=1000):
    """没放背景图时，自己画一张渐变图，效果一样能看"""
    pm = QPixmap(w, h)
    p = QPainter(pm)
    g = QLinearGradient(0, 0, w, h)
    g.setColorAt(0.0, QColor(28, 44, 74))
    g.setColorAt(0.5, QColor(38, 92, 120))
    g.setColorAt(1.0, QColor(70, 130, 96))
    p.fillRect(0, 0, w, h, g)
    # 一些花纹，方便看透明度
    p.setPen(QColor(255, 255, 255, 38))
    for x in range(0, w, 64):
        p.drawLine(x, 0, x, h)
    for y in range(0, h, 64):
        p.drawLine(0, y, w, y)
    p.setBrush(QColor(255, 190, 40, 210))
    p.setPen(Qt.NoPen)
    p.drawEllipse(w - 620, 60, 520, 520)
    p.end()
    return pm


def cover(pm, w, h):
    """把图裁成铺满 w×h（居中裁剪），相当于 CSS 的 cover"""
    if w <= 0 or h <= 0:
        return pm
    s = pm.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    return s.copy((s.width() - w) // 2, (s.height() - h) // 2, w, h)


def cheap_blur(pm, factor=10):
    """便宜的模糊：缩小再放大（够用，而且不慢）"""
    w, h = max(1, pm.width()), max(1, pm.height())
    small = pm.scaled(max(1, w // factor), max(1, h // factor),
                      Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    return small.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


# ============================================================
#  玻璃窗口：无边框 + 圆角 + 背景图
# ============================================================
class GlassWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("StatGI 试水版 · PySide6")
        self.resize(960, 700)
        self.setMinimumSize(720, 520)

        # 无边框 + 背景透明（这样圆角才是真的圆角，带抗锯齿）
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self._radius = 14
        self._bg_src = None
        self._bg_cache = None
        self._bg_key = None
        self._drag_pos = None

        self._load_bg()
        self._build()

    # ---------- 背景图 ----------
    def _load_bg(self):
        if os.path.exists(BG_IMAGE):
            pm = QPixmap(BG_IMAGE)
            if not pm.isNull():
                self._bg_src = pm
                return
        self._bg_src = make_default_bg()

    def _bg(self):
        """按当前窗口尺寸生成铺满的背景图（带缓存）"""
        w, h = self.width(), self.height()
        key = (w, h)
        if self._bg_key != key:
            self._bg_cache = cover(self._bg_src, w, h)
            self._bg_key = key
        return self._bg_cache

    def resizeEvent(self, e):
        self._bg_key = None
        super().resizeEvent(e)
        if hasattr(self, "sidebar"):
            self.sidebar.refresh_bg()      # 侧栏那块模糊图要重做
        if hasattr(self, "grip"):
            self.grip.move(self.width() - self.grip.width(),
                           self.height() - self.grip.height())

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
                            self._radius, self._radius)
        p.setClipPath(path)
        p.drawPixmap(0, 0, self._bg())          # ← 背景图
        # 整体压暗一点，保证字看得清
        p.fillRect(self.rect(), QColor(0, 0, 0, 40))
        p.setClipping(False)

    # ---------- 界面 ----------
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(TitleBar(self))

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.sidebar = Sidebar(self)
        body.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        self.stack.addWidget(PageLaunch(self))
        self.stack.addWidget(PageScroll(self))
        self.stack.addWidget(PageSettings(self))
        body.addWidget(self.stack, 1)

        holder = QWidget()
        holder.setLayout(body)
        root.addWidget(holder, 1)

        # 右下角拖拽改大小（Qt 自带，一行）
        self.grip = QSizeGrip(self)
        self.grip.setFixedSize(16, 16)


# ============================================================
#  标题条
# ============================================================
class TitleBar(QFrame):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self._drag = None
        self.setFixedHeight(46)
        self.setStyleSheet(
            f"QFrame {{ background: rgba(31,31,31,190);"
            f" border-top-left-radius: 14px; border-top-right-radius: 14px; }}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 8, 0)
        ico = QLabel("🍃")
        ico.setStyleSheet("font-size:16px;")
        lay.addWidget(ico)
        t = QLabel("StatGI 试水版（PySide6）")
        t.setStyleSheet(f"color:{TEXT}; font-family:'{FONT}'; font-size:14px; font-weight:600;")
        lay.addWidget(t)
        lay.addSpacing(12)
        s = QLabel("● 半透明玻璃 · 无边框 · 圆角")
        s.setStyleSheet(f"color:{DIM}; font-family:'{FONT}'; font-size:12px;")
        lay.addWidget(s)
        lay.addStretch(1)

        for text, cb, danger in (("—", lambda: win.showMinimized(), False),
                                 ("✕", lambda: win.close(), True)):
            b = QPushButton(text)
            b.setFixedSize(42, 30)
            b.setCursor(Qt.PointingHandCursor)
            hover = "#C0392B" if danger else "#3A3A3A"
            b.setStyleSheet(
                f"QPushButton {{ background:transparent; color:{TEXT}; border:none;"
                f" border-radius:6px; font-size:13px; }}"
                f"QPushButton:hover {{ background:{hover}; }}")
            b.clicked.connect(cb)
            lay.addWidget(b)

    # ---- 按住标题条拖动窗口 ----
    # 注意：标题条是子控件，鼠标事件不会冒泡到主窗口，
    # 所以拖动必须由标题条自己处理（放在主窗口上是拖不动的）。
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


# ============================================================
#  左侧栏（模糊玻璃）
# ============================================================
class Sidebar(QFrame):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setFixedWidth(190)
        self._blur_cache = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 14, 10, 14)
        lay.setSpacing(4)

        self.btns = []
        for i, (icon, name) in enumerate([("🚀", "启动"), ("🧪", "滚动测试"),
                                          ("⚙", "设置")]):
            b = QPushButton(f"  {icon}   {name}")
            b.setFixedHeight(40)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(self._btn_qss(False))
            b.clicked.connect(lambda _=False, idx=i: self.win.stack.setCurrentIndex(idx))
            lay.addWidget(b)
            self.btns.append(b)

        lay.addStretch(1)
        v = QLabel("V0.7 试水版")
        v.setStyleSheet(f"color:{DIM}; font-family:'{FONT}'; font-size:12px;")
        v.setAlignment(Qt.AlignCenter)
        lay.addWidget(v)

    def _btn_qss(self, active):
        bg = "rgba(76,194,255,45)" if active else "transparent"
        fg = ACCENT if active else TEXT
        return (f"QPushButton {{ background:{bg}; color:{fg}; border:none;"
                f" border-radius:8px; text-align:left; padding-left:14px;"
                f" font-family:'{FONT}'; font-size:14px; }}"
                f"QPushButton:hover {{ background:rgba(255,255,255,28); }}")

    def refresh_bg(self):
        self._blur_cache = None
        self.update()

    def paintEvent(self, e):
        # 侧栏 = 背景图的一块 + 模糊 + 压暗
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        bg = self.win._bg()
        r = self.rect()
        if self._blur_cache is None and bg is not None:
            crop = bg.copy(r)
            self._blur_cache = cheap_blur(crop, 12)
        if self._blur_cache is not None:
            p.drawPixmap(0, 0, self._blur_cache)
        p.fillRect(r, QColor(12, 12, 14, 150))      # 压暗
        p.end()


# ============================================================
#  通用卡片（半透明）
# ============================================================
def card_style(alpha=CARD_ALPHA, radius=12):
    r, g, b = CARD_RGB
    return (f"QFrame#card {{ background: rgba({r},{g},{b},{alpha});"
            f" border-radius:{radius}px; border:1px solid rgba(255,255,255,14); }}")


def make_card(parent, alpha=CARD_ALPHA):
    f = QFrame(parent)
    f.setObjectName("card")
    f.setStyleSheet(card_style(alpha))
    return f


def card_row(parent, icon, title, desc, right_widget=None, alpha=CARD_ALPHA):
    """一行设置卡片：[图标] 标题+说明 …… 右边控件"""
    c = make_card(parent, alpha)
    lay = QHBoxLayout(c)
    lay.setContentsMargins(14, 12, 14, 12)
    lay.setSpacing(12)

    ic = QLabel(icon)
    ic.setFixedSize(42, 42)
    ic.setAlignment(Qt.AlignCenter)
    ic.setStyleSheet("background: rgba(255,255,255,20); border-radius:12px; font-size:18px;")
    lay.addWidget(ic)

    mid = QVBoxLayout()
    mid.setSpacing(2)
    t = QLabel(title)
    t.setStyleSheet(f"color:{TEXT}; font-family:'{FONT}'; font-size:15px; font-weight:600;")
    d = QLabel(desc)
    d.setStyleSheet(f"color:{DIM}; font-family:'{FONT}'; font-size:12px;")
    mid.addWidget(t)
    mid.addWidget(d)
    lay.addLayout(mid, 1)

    if right_widget is not None:
        lay.addWidget(right_widget)
    c.setFixedHeight(70)
    return c


# ============================================================
#  页面 1：启动
# ============================================================
class PageLaunch(QWidget):
    def __init__(self, win):
        super().__init__(win)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(10)

        h = QLabel("启动")
        h.setStyleSheet(f"color:{ACCENT}; font-family:'{FONT}'; font-size:22px; font-weight:700;")
        lay.addWidget(h)

        # 大卡片
        c = make_card(self)
        v = QVBoxLayout(c)
        v.setContentsMargins(18, 16, 18, 16)
        t = QLabel("🍃  StatGI")
        t.setStyleSheet(f"color:{TEXT}; font-family:'{FONT}'; font-size:20px; font-weight:700;")
        v.addWidget(t)
        s = QLabel("● 未框选（自动检测游戏窗口）")
        s.setStyleSheet(f"color:{DIM}; font-family:'{FONT}'; font-size:13px;")
        v.addWidget(s)
        lay.addWidget(c)

        # 开始监测
        start_btn = QPushButton("开始")
        start_btn.setFixedSize(110, 38)
        start_btn.setCursor(Qt.PointingHandCursor)
        start_btn.setStyleSheet(
            f"QPushButton {{ background: rgba(76,194,255,200); color:#08222E; border:none;"
            f" border-radius:8px; font-family:'{FONT}'; font-size:15px; font-weight:600; }}"
            f"QPushButton:hover {{ background: rgba(76,194,255,235); }}")
        lay.addWidget(card_row(self, "▶", "开始监测", "自动找到游戏窗口并识别掉落收益", start_btn))

        # 清空
        dd = QComboBox()
        dd.addItems(["清空今日数据", "清空全部数据"])
        dd.setFixedWidth(150)
        dd.setStyleSheet(
            f"QComboBox {{ background: rgba(255,255,255,22); color:{TEXT}; border:none;"
            f" border-radius:8px; padding:6px 10px; font-family:'{FONT}'; font-size:13px; }}"
            f"QComboBox::drop-down {{ border:none; width:22px; }}"
            f"QComboBox QAbstractItemView {{ background:#242424; color:{TEXT};"
            f" selection-background-color:{ACCENT}; }}")
        clr = QPushButton("清空")
        clr.setFixedSize(80, 34)
        clr.setCursor(Qt.PointingHandCursor)
        clr.setStyleSheet(
            f"QPushButton {{ background: rgba(255,255,255,26); color:{TEXT}; border:none;"
            f" border-radius:8px; font-family:'{FONT}'; font-size:14px; }}"
            f"QPushButton:hover {{ background: rgba(255,255,255,46); }}")
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)
        rl.addWidget(dd)
        rl.addWidget(clr)
        lay.addWidget(card_row(self, "🧹", "清空", "选好要清空的内容，再点右边按钮", row))

        # 折叠区（Qt 里 Accordion 也是自己拼，但很简单）
        lay.addWidget(Accordion(self, "🎯", "重新框选",
                                "手动指定要识别的屏幕区域（一般都不用）",
                                ["重新框选区域", "诊断截图"]))
        lay.addStretch(1)


# ============================================================
#  页面 2：滚动测试（看拖影）
# ============================================================
class PageScroll(QWidget):
    def __init__(self, win):
        super().__init__(win)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(10)

        h = QLabel("滚动测试")
        h.setStyleSheet(f"color:{ACCENT}; font-family:'{FONT}'; font-size:22px; font-weight:700;")
        lay.addWidget(h)

        tip = QLabel("300 行高饱和色块。点下面的按钮自动滚动 —— 盯着看有没有拖影／残影。")
        tip.setStyleSheet(f"color:{DIM}; font-family:'{FONT}'; font-size:13px;")
        lay.addWidget(tip)

        bar = QHBoxLayout()
        self.btn_auto = QPushButton("▶  自动滚动 30 次")
        self.btn_auto.setFixedSize(180, 36)
        self.btn_auto.setCursor(Qt.PointingHandCursor)
        self.btn_auto.setStyleSheet(
            f"QPushButton {{ background: rgba(76,194,255,200); color:#08222E; border:none;"
            f" border-radius:8px; font-family:'{FONT}'; font-size:14px; font-weight:600; }}"
            f"QPushButton:hover {{ background: rgba(76,194,255,235); }}")
        bar.addWidget(self.btn_auto)
        self.lbl_state = QLabel("")
        self.lbl_state.setStyleSheet(f"color:{DIM}; font-family:'{FONT}'; font-size:13px;")
        bar.addWidget(self.lbl_state)
        bar.addStretch(1)
        lay.addLayout(bar)

        # 滚动区
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        sc.setStyleSheet("QScrollArea { background: transparent; border:none; }"
                         "QScrollArea > QWidget > QWidget { background: transparent; }")
        sc.viewport().setAutoFillBackground(False)

        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(0)
        for i in range(300):
            row = QFrame()
            row.setFixedHeight(30)
            hue = (i * 37) % 360
            c = QColor.fromHsv(hue, 215, 240)
            row.setStyleSheet(f"background: rgb({c.red()},{c.green()},{c.blue()});")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(10, 0, 10, 0)
            lb = QLabel(f"第 {i+1} 行")
            lb.setStyleSheet("color: rgba(0,0,0,150); font-size:12px;")
            rl.addWidget(lb)
            il.addWidget(row)
        sc.setWidget(inner)
        lay.addWidget(sc, 1)

        # 自动滚动
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._auto_step)
        self._left = 0
        self._sc = sc
        self.btn_auto.clicked.connect(self._auto_start)

    def _auto_start(self):
        self._left = 30
        self._timer.start(120)

    def _auto_step(self):
        if self._left <= 0:
            self._timer.stop()
            self.lbl_state.setText("滚动结束 —— 刚才有没有拖影？")
            return
        self.lbl_state.setText(f"滚动中… 还剩 {self._left} 次")
        sb = self._sc.verticalScrollBar()
        if sb.value() >= sb.maximum() - 2:
            sb.setValue(0)
        else:
            sb.setValue(sb.value() + 30)
        self._left -= 1


# ============================================================
#  页面 3：设置（看控件是不是现成的）
# ============================================================
class PageSettings(QWidget):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(10)

        h = QLabel("设置")
        h.setStyleSheet(f"color:{ACCENT}; font-family:'{FONT}'; font-size:22px; font-weight:700;")
        lay.addWidget(h)

        # 卡片透明度滑块 —— 拖动实时改所有卡片的透明度
        self.alpha = QSlider(Qt.Horizontal)
        self.alpha.setRange(0, 255)
        self.alpha.setValue(CARD_ALPHA)
        self.alpha.setFixedWidth(180)
        self.alpha.setStyleSheet(
            "QSlider::groove:horizontal { height:6px; background: rgba(255,255,255,30);"
            " border-radius:3px; }"
            f"QSlider::sub-page:horizontal {{ background:{ACCENT}; border-radius:3px; }}"
            f"QSlider::handle:horizontal {{ background:{ACCENT}; width:16px; height:16px;"
            f" margin:-6px 0; border-radius:8px; }}")
        self.lbl_alpha = QLabel(f"{int(CARD_ALPHA / 255 * 100)}%")
        self.lbl_alpha.setFixedWidth(42)
        self.lbl_alpha.setStyleSheet(f"color:{ACCENT}; font-family:'{FONT}'; font-size:13px;")
        self.alpha.valueChanged.connect(self._on_alpha)
        holder = QWidget()
        hl = QHBoxLayout(holder)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(self.alpha)
        hl.addWidget(self.lbl_alpha)
        self.row_alpha = card_row(self, "🌓", "卡片透明度",
                                  "拖一下 —— 所有卡片实时变透明", holder)
        lay.addWidget(self.row_alpha)

        # 下拉框
        dd = QComboBox()
        dd.addItems(["经典深黑", "深夜蓝", "墨绿", "自定义…"])
        dd.setFixedWidth(150)
        dd.setStyleSheet(
            f"QComboBox {{ background: rgba(255,255,255,22); color:{TEXT}; border:none;"
            f" border-radius:8px; padding:6px 10px; font-family:'{FONT}'; font-size:13px; }}"
            f"QComboBox QAbstractItemView {{ background:#242424; color:{TEXT};"
            f" selection-background-color:{ACCENT}; }}")
        lay.addWidget(card_row(self, "🎨", "背景颜色", "窗口背景色", dd))

        # 输入框
        ed = QLineEdit("50")
        ed.setFixedWidth(90)
        ed.setAlignment(Qt.AlignCenter)
        ed.setStyleSheet(
            f"QLineEdit {{ background: rgba(255,255,255,22); color:{TEXT}; border:none;"
            f" border-radius:8px; padding:6px 10px; font-family:'{FONT}'; font-size:13px; }}")
        lay.addWidget(card_row(self, "⏱", "检测间隔", "每多少毫秒检查一次画面", ed))

        # 开关（QCheckBox 穿个皮肤）
        cb = Switch()
        cb.setChecked(True)
        wrap = QWidget()
        wl = QHBoxLayout(wrap)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.addWidget(cb)
        lay.addWidget(card_row(self, "➕", "自动登记新材料",
                               "遇到材料库里没有的名字时自动加进去", wrap))

        lay.addStretch(1)

    def _on_alpha(self, v):
        self.lbl_alpha.setText(f"{int(v / 255 * 100)}%")
        # 所有页面的卡片一起变（含折叠区）
        for w in self.win.findChildren(QFrame):
            if w.objectName() == "card":
                w.setStyleSheet(card_style(v))


class Switch(QCheckBox):
    """一个看起来像开关的复选框（Qt 里没有现成的 Switch，但这个够用）"""

    def __init__(self):
        super().__init__()
        self.setFixedSize(54, 28)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(f"""
            QCheckBox {{ spacing:0; }}
            QCheckBox::indicator {{ width:46px; height:24px; border-radius:12px;
                background: #5A5A5A; }}
            QCheckBox::indicator:checked {{ background: {ACCENT}; }}
        """)


# ============================================================
#  折叠区
# ============================================================
class Accordion(QFrame):
    def __init__(self, parent, icon, title, desc, buttons):
        super().__init__(parent)
        self.setObjectName("card")
        self.setStyleSheet(card_style())
        self._open = False

        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(14, 12, 14, 12)
        self.v.setSpacing(8)

        head = QHBoxLayout()
        ic = QLabel(icon)
        ic.setFixedSize(42, 42)
        ic.setAlignment(Qt.AlignCenter)
        ic.setStyleSheet("background: rgba(255,255,255,20); border-radius:12px; font-size:18px;")
        head.addWidget(ic)
        mid = QVBoxLayout()
        t = QLabel(title)
        t.setStyleSheet(f"color:{TEXT}; font-family:'{FONT}'; font-size:15px; font-weight:600;")
        d = QLabel(desc)
        d.setStyleSheet(f"color:{DIM}; font-family:'{FONT}'; font-size:12px;")
        mid.addWidget(t)
        mid.addWidget(d)
        head.addLayout(mid, 1)
        self.arrow = QLabel("▸")
        self.arrow.setStyleSheet(f"color:{DIM}; font-size:15px;")
        head.addWidget(self.arrow)
        self.v.addLayout(head)

        self.body = QWidget()
        bl = QHBoxLayout(self.body)
        bl.setContentsMargins(0, 0, 0, 0)
        for b in buttons:
            btn = QPushButton(b)
            btn.setFixedHeight(34)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton {{ background: rgba(255,255,255,26); color:{TEXT}; border:none;"
                f" border-radius:8px; padding:0 16px; font-family:'{FONT}'; font-size:13px; }}"
                f"QPushButton:hover {{ background: rgba(255,255,255,46); }}")
            bl.addWidget(btn)
        bl.addStretch(1)
        self.body.hide()
        self.v.addWidget(self.body)

        for w in (self, ic, t, d, self.arrow):
            w.setCursor(Qt.PointingHandCursor)
            w.mousePressEvent = self._toggle

    def _toggle(self, _e=None):
        self._open = not self._open
        self.body.setVisible(self._open)
        self.arrow.setText("▾" if self._open else "▸")


# ============================================================
def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("StatGI 试水版")
    w = GlassWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
