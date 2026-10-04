# -*- coding: utf-8 -*-
"""每日收益柱状图（深色版，风格参考 DeepSeek 用量页那种"很空"的图）。

设计要点（照着 DeepSeek 那张图的观感，改成深色主题）：
    · 柱子**细**、圆角顶、自上而下的渐变
    · 横向网格线**极淡**，只留几条；纵轴刻度用简写（1.2万）
    · 横轴日期**稀疏**标注（不是每天都标）
    · 鼠标悬停：柱子高亮 + 一条淡色竖带 + 小气泡显示"日期 + 数值"
    · 没有边框、没有满屏网格

⚠ 只用 qt_theme 里的颜色，跟着主题走；不联网、不读文件。
"""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QLinearGradient,
                           QPainter, QPainterPath, QPen)
from PySide6.QtWidgets import QSizePolicy, QWidget

from qt_theme import ACCENT, BORDER, CARD_INNER, DIM, TEXT, hex_rgb

_PAD_L = 58.0      # 左边留给纵轴刻度
_PAD_R = 14.0
_PAD_T = 18.0      # 上边留给悬停气泡
_PAD_B = 30.0      # 下边留给日期
_MIN_BAR = 2.0
_MAX_BAR = 18.0
_BAR_RATIO = 0.42


def qc(color, alpha=255):
    """颜色 + 透明度 → QColor。

    ⚠ **不能用 `qt_theme.rgba()`**：它返回的是给样式表用的字符串
      `"rgba(r,g,b,a)"`，`QColor()` 解析不了 → 直接变黑（真踩过，
      第一版柱子全是黑的）。这里自己从 `hex_rgb()` 造。
    """
    r, g, b = hex_rgb(color)
    c = QColor(r, g, b)
    c.setAlpha(int(max(0, min(255, int(alpha)))))
    return c


def compact(v, force_wan=False):
    """数字怎么显示。

    ⚠ 用户 2026-10-04 明确：**上万也别简写成"万"，要显示具体数字**
      （原来那套 `1.2万` 的简写全撤了，一律写全 + 千分位）。
      `force_wan` 参数留着只为兼容旧调用，现在不起作用。
    """
    try:
        n = int(round(float(v)))
    except Exception:
        return "0"
    return f"{n:,}"


def nice_max(v):
    """把纵轴上限取成好看的整数（1 / 2 / 2.5 / 5 / 10 × 10^n）"""
    if v <= 0:
        return 1
    exp = math.floor(math.log10(v))
    base = 10 ** exp
    for m in (1, 2, 2.5, 5, 10):
        if v <= m * base + 1e-9:
            return m * base
    return 10 * base


def axis_label(v, vmax=None):
    """纵轴刻度：一律写**具体数字**（用户 2026-10-04 要求，不许简写成"万"）"""
    return compact(v)


class DailyBarChart(QWidget):
    """一根柱子 = 一天。`set_rows()` 喂数据，`key` 指定画哪个字段。"""

    def __init__(self, parent=None, unit="", min_height=210):
        super().__init__(parent)
        self.unit = unit
        self._rows = []
        self._hover = -1
        self._mouse = None          # 鼠标位置（气泡跟着它走）
        self._empty_text = "这段时间还没有收益"
        self.setMouseTracking(True)
        self.setMinimumHeight(min_height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    # ------------------------------------------------------------ 数据
    def set_rows(self, rows, key):
        """rows 用 `svc_daily.daily_totals()` 的返回；key = "mora"/"artifact"…"""
        out = []
        for r in (rows or []):
            try:
                v = int(r.get(key) or 0)
            except Exception:
                continue
            if not math.isfinite(v):          # 万一数据里有 NaN/inf，别让它进画图
                v = 0
            out.append({"date": str(r.get("date", "")),
                        "label": str(r.get("label", "")),
                        "value": max(0, v)})
        self._rows = out
        self._hover = -1
        self.update()

    def set_empty_text(self, text):
        self._empty_text = str(text)
        self.update()

    def rows(self):
        return list(self._rows)

    # ------------------------------------------------------------ 几何
    def _pad_l(self):
        """左边留给纵轴刻度的宽度。

        ⚠ 数字改成写全之后会变宽（"1,000,000" 比 "100万" 宽得多），
          所以按**当前上限那个最长刻度**量出来再定，别写死 58px
          （写死的话大数字会被裁掉）。
        """
        f = QFont(self.font())
        f.setPointSize(9)
        fm = QFontMetrics(f)
        return max(_PAD_L, float(fm.horizontalAdvance(compact(self._vmax())) + 16))

    def _plot(self):
        pad_l = self._pad_l()
        return QRectF(pad_l, _PAD_T,
                      max(1.0, self.width() - pad_l - _PAD_R),
                      max(1.0, self.height() - _PAD_T - _PAD_B))

    def _vmax(self):
        """纵轴上限（没有数据时给 1，避免除零）"""
        if not self._rows:
            return 1
        return nice_max(max(r["value"] for r in self._rows))

    def _slot_w(self):
        n = len(self._rows)
        return (self._plot().width() / n) if n else 0.0

    def _bar_w(self):
        return max(_MIN_BAR, min(self._slot_w() * _BAR_RATIO, _MAX_BAR))

    def _bar_rect(self, i, vmax):
        """第 i 根柱子的矩形（含悬停时的高亮不算在里面）"""
        plot = self._plot()
        slot = self._slot_w()
        bw = self._bar_w()
        cx = plot.left() + slot * (i + 0.5)
        val = self._rows[i]["value"]
        h = 0.0 if vmax <= 0 else plot.height() * (val / vmax)
        if val > 0:
            h = max(2.0, h)                      # 有值就至少看得见
        return QRectF(cx - bw / 2.0, plot.bottom() - h, bw, h)

    def _index_at(self, x):
        if not self._rows:
            return -1
        plot = self._plot()
        slot = self._slot_w()
        if slot <= 0 or x < plot.left() or x > plot.right():
            return -1
        i = int((x - plot.left()) / slot)
        return max(0, min(len(self._rows) - 1, i))

    # ------------------------------------------------------------ 交互
    def _set_hover(self, i):
        """设置当前悬停到第几根柱子（-1 = 没有）"""
        self._hover = i
        self.update()

    def mouseMoveEvent(self, e):
        pos = e.position()
        self._mouse = (float(pos.x()), float(pos.y()))
        self._hover = self._index_at(pos.x())
        # ⚠ **整张重画**，别只重画"那一条竖带"。
        #   2026-10-04 用户报的："滑过去所有的弹窗全都没有消失" ——
        #   原因就是气泡画在竖带外面，旧气泡那块没被重画，留在屏幕上越积越多。
        #   这张图很小，整张重画不到 1ms，不值得为省这点去算脏矩形。
        self.update()

    def leaveEvent(self, e):
        self._mouse = None
        self._hover = -1
        self.update()

    def bubble_text(self):
        """当前该显示的气泡文字（没悬停返回 ""）"""
        if self._hover < 0 or self._hover >= len(self._rows):
            return ""
        r = self._rows[self._hover]
        return f"{r['date']}　{compact(r['value'])}{self.unit}"

    def bubble_rect(self, text, fm):
        """气泡的矩形（**跟着鼠标**，并夹在控件里，不让它跑出去）。

        ⚠ 不是顶在柱子正上方 —— 一个月 30 天时每根柱子才 20 多像素宽，
          气泡顶上去就把整列都盖住了（用户 2026-10-04 要求的）。
        """
        tw = fm.horizontalAdvance(text) + 20.0
        th = 28.0
        if self._mouse is not None:
            mx, my = self._mouse
            tx, ty = mx + 16.0, my - th - 14.0     # 默认：鼠标右上
            if ty < 4:                              # 顶到上边了 → 换到鼠标下方
                ty = my + 18.0
        else:                                       # 没有鼠标（测试/键盘）→ 放柱子上面
            rect = self._bar_rect(self._hover, self._vmax()) \
                if self._hover >= 0 else QRectF(0, 0, 0, 0)
            tx, ty = rect.center().x() - tw / 2.0, rect.top() - th - 8.0
        tx = min(max(4.0, tx), max(4.0, self.width() - tw - 4.0))
        ty = min(max(4.0, ty), max(4.0, self.height() - th - 4.0))
        return QRectF(tx, ty, tw, th)

    # ------------------------------------------------------------ 画
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        plot = self._plot()

        if not self._rows:
            p.setPen(QPen(QColor(DIM)))
            f = QFont(self.font())
            f.setPointSize(10)
            p.setFont(f)
            p.drawText(self.rect(), Qt.AlignCenter, self._empty_text)
            return

        vmax = self._vmax()
        # 网格段数：小整数范围（狗粮常常是 1~5）就按整数分段，
        # 否则会出现 5 / 4 / 2 / 1 / 0 这种被四舍五入过的刻度
        steps = max(1, int(vmax)) if vmax <= 5 else 4

        # ---- 横向网格线 + 纵轴刻度 ----
        f = QFont(self.font())
        f.setPointSize(9)
        p.setFont(f)
        for k in range(steps + 1):
            y = plot.bottom() - plot.height() * (k / steps)
            if k > 0:
                p.setPen(QPen(qc(TEXT, 16), 1))
                p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            else:
                p.setPen(QPen(qc(TEXT, 45), 1))
                p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            label = axis_label(vmax * k / steps, vmax)
            p.setPen(QPen(qc(DIM)))
            p.drawText(QRectF(0, y - 9, _PAD_L - 8, 18),
                       Qt.AlignRight | Qt.AlignVCenter, label)

        # ---- 柱子 ----
        grad = QLinearGradient(0, plot.top(), 0, plot.bottom())
        grad.setColorAt(0.0, qc(ACCENT, 235))
        grad.setColorAt(1.0, qc(ACCENT, 105))
        grad_hi = QLinearGradient(0, plot.top(), 0, plot.bottom())
        grad_hi.setColorAt(0.0, qc(ACCENT, 255))
        grad_hi.setColorAt(1.0, qc(ACCENT, 150))

        bw = self._bar_w()
        radius = 3.0 if bw >= 6 else (1.5 if bw >= 3 else 0.0)

        # 悬停的那条淡色竖带（画在柱子下面）
        if self._hover >= 0:
            slot = self._slot_w()
            cx = plot.left() + slot * (self._hover + 0.5)
            band = QRectF(cx - slot / 2.0, plot.top(),
                          slot, plot.height())
            p.setPen(Qt.NoPen)
            p.setBrush(qc(ACCENT, 26))
            p.drawRoundedRect(band, 5, 5)

        p.setPen(Qt.NoPen)
        for i, r in enumerate(self._rows):
            rect = self._bar_rect(i, vmax)
            if rect.height() <= 0:
                continue
            p.setBrush(grad_hi if i == self._hover else grad)
            if radius > 0:
                p.drawRoundedRect(rect, radius, radius)
            else:
                p.drawRect(rect)

        # ---- 横轴日期（稀疏）----
        n = len(self._rows)
        step = max(1, math.ceil(n / 7.0))
        for i, r in enumerate(self._rows):
            if i % step and i != self._hover and i != n - 1:
                continue
            slot = self._slot_w()
            cx = plot.left() + slot * (i + 0.5)
            hot = (i == self._hover)
            p.setPen(QPen(qc(TEXT if hot else DIM)))
            p.drawText(QRectF(cx - slot, plot.bottom() + 6, slot * 2, 18),
                       Qt.AlignHCenter | Qt.AlignTop, r["label"])

        # ---- 悬停气泡（跟着鼠标走，见 bubble_rect 的说明）----
        text = self.bubble_text()
        if text:
            f2 = QFont(self.font())
            f2.setPointSize(10)
            f2.setBold(True)
            p.setFont(f2)
            bubble = self.bubble_rect(text, p.fontMetrics())
            path = QPainterPath()
            path.addRoundedRect(bubble, 7, 7)
            p.setPen(QPen(qc(TEXT, 40), 1))
            p.setBrush(qc(CARD_INNER, 252))
            p.drawPath(path)
            p.setPen(QPen(qc(TEXT)))
            p.drawText(bubble, Qt.AlignCenter, text)
