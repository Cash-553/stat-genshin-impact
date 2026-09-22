# -*- coding: utf-8 -*-
"""StatGI Qt 版 · 监测悬浮窗（收益统计条）

按「动态项目列表」渲染：项目从 :mod:`bar_items` 读，能加能删，
每个项目有自己的字体 / 卡片设置，另外还有整体窗口设置。

真·逐像素透明（WA_TranslucentBackground），OBS 里窗口捕获不会有黑边。
"""
from PySide6.QtCore import Qt, QTimer, QRectF, Signal
from PySide6.QtGui import (QPainter, QPainterPath, QColor, QPen, QFont,
                           QPixmap)
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
                               QLabel)

import paths
import qt_theme as T
import bar_items

ICONS_DIR = paths.icons_dir()

# 阴影画的边距（别贴着窗口边切掉）
SHADOW_PAD = 8

# 拖动时吸附到几像素
GRID = 8


def _align(qt_align):
    return {"center": Qt.AlignCenter, "left": Qt.AlignLeft,
            "right": Qt.AlignRight}.get(str(qt_align), Qt.AlignCenter)


def _qfont(family, size, bold):
    f = QFont(str(family or "Microsoft YaHei UI"))
    f.setPixelSize(max(6, int(size)))
    f.setBold(bool(bold))
    return f


class ItemCard(QWidget):
    """一个监测项目：图标 / 标题 / 数值，样式全部来自配置。

    自由摆放模式下可以拖动改位置。
    """

    moved = Signal(int, int)          # 拖动结束 -> 新位置

    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.item = dict(item)
        self._value_text = ""
        self._icon = None
        self._icon_key = None
        self._editable = False
        self._drag = None
        self.setMouseTracking(True)

        self.v = QVBoxLayout(self)
        self.icon_label = QLabel()
        self.title_label = QLabel()
        self.value_label = QLabel()
        self.rate_label = QLabel()
        for w in (self.icon_label, self.title_label, self.value_label,
                  self.rate_label):
            w.setAttribute(Qt.WA_TranslucentBackground, True)
        self.rate_label.setVisible(False)
        self._built = None            # 记录当前是按哪种布局搭的
        self._build_inner()
        self.apply_item(self.item)

    # ---------- 内部布局（图标位置 / 标题上下会变，所以要能重搭） ----------
    def _clear(self, lay):
        while lay.count():
            it = lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)

    def _build_inner(self, icon_pos="top", title_below=False):
        """按图标位置和标题上下重搭内部布局"""
        key = (icon_pos, bool(title_below))
        if self._built == key:
            return
        self._built = key
        self._clear(self.v)
        old = self.layout()
        if old is not None and old is not self.v:
            QWidget().setLayout(old)

        self.text_col = QVBoxLayout()
        self.text_col.setSpacing(1)
        if title_below:
            self.text_col.addWidget(self.value_label, 1)
            self.text_col.addWidget(self.title_label, 1)
        else:
            self.text_col.addWidget(self.title_label, 1)
            self.text_col.addWidget(self.value_label, 1)
        self.text_col.addWidget(self.rate_label, 0)

        if icon_pos in ("left", "right"):
            row = QHBoxLayout()
            row.setSpacing(6)
            # 竖排时 label 宽度贴着图标，居中即可；
            # 左右排时 label 高度撑满，要竖向居中，否则图标顶在卡片上边
            self.icon_label.setAlignment(Qt.AlignCenter)
            if icon_pos == "left":
                row.addWidget(self.icon_label, 0)
                row.addLayout(self.text_col, 1)
            else:
                row.addLayout(self.text_col, 1)
                row.addWidget(self.icon_label, 0)
            self.v.addLayout(row)
        elif icon_pos == "bottom":
            # 「下方」：文字在上、图标在下。同样要水平居中 ——
            # label 宽度撑满卡片，不设对齐 QPixmap 会贴左边
            self.icon_label.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            self.v.addLayout(self.text_col, 1)
            self.v.addWidget(self.icon_label, 0)
        else:
            # 「上方」：label 宽度撑满卡片，必须水平居中 ——
            # 不设的话 QPixmap 默认左对齐，图标会跑到左上角
            self.icon_label.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            self.v.addWidget(self.icon_label, 0)
            self.v.addLayout(self.text_col, 1)

    def set_editable(self, on):
        self._editable = bool(on)
        self._drag = None
        self.setCursor(Qt.SizeAllCursor if on else Qt.ArrowCursor)
        self.update()

    def apply_item(self, item):
        self.item = dict(item)
        it = self.item

        w = int(it.get("width", 165))
        h = int(it.get("height", 77))
        self.setFixedSize(max(30, w), max(24, h))

        self._build_inner(str(it.get("icon_pos") or "top"),
                          bool(it.get("title_below")))

        p = max(0, int(it.get("padding", 10)))
        self.v.setContentsMargins(p, p, p, p)
        self.v.setSpacing(2)
        self.text_col.setSpacing(1)

        # ---- 图标 ----
        show_i = bool(it.get("show_icon", False))
        self.icon_label.setVisible(show_i)
        if show_i:
            size = int(it.get("icon_size", 34))
            if str(it.get("icon_pos")) in ("left", "right"):
                self.icon_label.setFixedSize(size, size)
            else:
                self.icon_label.setFixedHeight(size + 4)
            self.set_icon(str(it.get("icon") or ""), size)
        else:
            self.icon_label.setPixmap(QPixmap())

        # ---- 标题 ----
        show_t = bool(it.get("show_title", True)) and bool(it.get("title"))
        self.title_label.setVisible(show_t)
        self.title_label.setText(str(it.get("title") or ""))
        self.title_label.setAlignment(_align(it.get("title_align")))
        self.title_label.setFont(_qfont(it.get("title_font"),
                                        it.get("title_size", 13),
                                        it.get("title_bold", False)))
        c = QColor(str(it.get("title_color") or T.DIM))
        self.title_label.setStyleSheet(
            f"color: rgba({c.red()},{c.green()},{c.blue()},255);"
            " background: transparent;")

        # ---- 数值 ----
        show_v = bool(it.get("show_value", True))
        self.value_label.setVisible(show_v)
        self.value_label.setAlignment(_align(it.get("value_align")))
        self.value_label.setFont(_qfont(it.get("value_font"),
                                        it.get("value_size", 30),
                                        it.get("value_bold", True)))
        c2 = QColor(str(it.get("value_color") or T.TEXT))
        self.value_label.setStyleSheet(
            f"color: rgba({c2.red()},{c2.green()},{c2.blue()},255);"
            " background: transparent;")
        self.set_value(self._value_text)
        self.update()

    def set_icon(self, fname, size):
        if fname == self._icon_key and self._icon is not None:
            return
        self._icon_key = fname
        path = ICONS_DIR / fname if fname else None
        if path is not None and path.exists():
            pm = QPixmap(str(path))
            if not pm.isNull():
                self._icon = pm.scaled(size, size, Qt.KeepAspectRatio,
                                       Qt.SmoothTransformation)
                self.icon_label.setPixmap(self._icon)
                self.icon_label.setStyleSheet("background: transparent;")
                return
        self._icon = None
        self.icon_label.setPixmap(QPixmap())

    def set_value(self, text, rate=None):
        self._value_text = text or ""
        if self.value_label.text() != self._value_text:
            self.value_label.setText(self._value_text)
        # 速率行（show_rate 开了才有）
        show = bool(self.item.get("show_rate")) and rate is not None
        self.rate_label.setVisible(show)
        if show:
            it = self.item
            self.rate_label.setText(str(rate))
            self.rate_label.setAlignment(_align(it.get("value_align")))
            c = QColor(str(it.get("title_color") or "#C8CCD4"))
            self.rate_label.setFont(_qfont(it.get("title_font"),
                                           max(9, int(it.get("title_size", 13)) - 1),
                                           False))
            self.rate_label.setStyleSheet(
                f"color: rgba({c.red()},{c.green()},{c.blue()},190);"
                " background: transparent;")

    # ---------- 自由摆放：拖动 ----------
    def mousePressEvent(self, e):
        if not self._editable or e.button() != Qt.LeftButton:
            e.ignore()
            return
        self._drag = e.position().toPoint()
        self.setCursor(Qt.ClosedHandCursor)
        e.accept()

    def mouseMoveEvent(self, e):
        if not self._editable or self._drag is None:
            e.ignore()
            return
        np = self.mapToParent(e.position().toPoint() - self._drag)
        x = max(0, int(round(np.x() / GRID)) * GRID)
        y = max(0, int(round(np.y() / GRID)) * GRID)
        self.move(x, y)
        e.accept()

    def mouseReleaseEvent(self, e):
        if self._drag is not None:
            self._drag = None
            self.setCursor(Qt.SizeAllCursor if self._editable else Qt.ArrowCursor)
            self.moved.emit(self.x(), self.y())
            e.accept()

    # ---------- 画卡片 ----------
    def paintEvent(self, e):
        it = self.item
        alpha = int(it.get("bg_alpha", 158))
        bordered = bool(it.get("border", True))
        shadow = bool(it.get("shadow", False))
        if alpha > 0 or bordered or shadow or self._editable:
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing, True)
            w, h = self.width(), self.height()
            inset = SHADOW_PAD if shadow else 0
            bw = float(it.get("border_width", 1)) if bordered else 0.0
            r = float(it.get("radius", 14))
            cw, ch = w - inset * 2, h - inset * 2
            r = min(r, (cw - bw) / 2.0, (ch - bw) / 2.0)
            rect = QRectF(inset + bw / 2, inset + bw / 2, cw - bw, ch - bw)
            path = QPainterPath()
            path.addRoundedRect(rect, r, r)

            if shadow:
                for i in range(inset, 0, -1):
                    a = max(0, int(46 * (i / inset) ** 2))
                    if a <= 0:
                        continue
                    sp = QPainterPath()
                    sp.addRoundedRect(rect.adjusted(-i, -i + 1, i, i + 1),
                                      r + i, r + i)
                    p.fillPath(sp, QColor(0, 0, 0, a))

            if alpha > 0:
                c = QColor(str(it.get("bg_color") or "#14141A"))
                c.setAlpha(max(0, min(255, alpha)))
                p.fillPath(path, c)
            if bordered:
                bc = QColor(str(it.get("border_color") or "#FFFFFF"))
                bc.setAlpha(max(0, min(255, int(it.get("border_alpha", 31)))))
                pen = QPen(bc)
                pen.setWidthF(max(0.5, bw))
                p.setPen(pen)
                p.drawPath(path)
            if self._editable:
                pen = QPen(QColor(T.ACCENT))
                pen.setWidth(1)
                pen.setStyle(Qt.DashLine)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawRect(0, 0, w - 1, h - 1)
            p.end()


class StatBarWindow(QWidget):
    """监测悬浮窗：内容、样式、排列全部来自 bar_items 的配置。"""

    def __init__(self, state, on_closed=None):
        super().__init__()
        self.state = state
        self._on_closed = on_closed
        self._drag = None
        self._cards = []
        self._free_items = []
        self._editable = False
        self._cfg = bar_items.load()
        self._last = None

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                            | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowTitle("监测悬浮窗")

        self._lay = None
        self.reload()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(500)
        self.refresh()

    # ---------- 按配置重建 ----------
    def reload(self):
        """重新读配置并重建界面（设置界面上改了东西就调这个）"""
        self._cfg = bar_items.load()
        win = self._cfg.get("window") or {}

        for c in self._cards:
            c.setParent(None)
            c.deleteLater()
        self._cards = []
        old = self.layout()
        if old is not None:
            QWidget().setLayout(old)

        kind = str(win.get("layout") or "column")
        pad = max(0, int(win.get("padding", 10)))
        gap = max(0, int(win.get("spacing", 8)))
        free = (kind == "free")
        self._free_items = []
        if free:
            lay = None                       # 自由摆放：不要布局管理器
        elif kind == "grid":
            lay = QGridLayout(self)
        elif kind == "row":
            lay = QHBoxLayout(self)
        else:
            lay = QVBoxLayout(self)
        if lay is not None:
            lay.setContentsMargins(pad, pad, pad, pad)
            lay.setSpacing(gap)

        idx = 0
        for it in self._cfg.get("items") or []:
            if not it.get("visible", True):
                continue
            c = ItemCard(it, self)
            c.moved.connect(lambda x, y, i=it: self._on_card_moved(i, x, y))
            self._cards.append(c)
            if free:
                self._free_items.append((c, it))
            elif kind == "grid":
                lay.addWidget(c, idx // 2, idx % 2)
            else:
                lay.addWidget(c)
            idx += 1
        self._lay = lay

        for c in self._cards:
            c.set_editable(self._editable)

        try:
            op = float(win.get("opacity", 1.0))
        except Exception:
            op = 1.0
        self.setWindowOpacity(max(0.2, min(1.0, op)))
        self.setWindowFlag(Qt.WindowStaysOnTopHint,
                           bool(win.get("always_on_top", True)))

        w = int(win.get("width", 0) or 0)
        h = int(win.get("height", 0) or 0)
        if w > 0 and h > 0 and not free:
            self.setFixedSize(w, h)
        else:
            self.setMinimumSize(0, 0)
            self.setMaximumSize(16777215, 16777215)
            self.adjustSize()
            if free:
                self._place_free(pad, gap)
                self._fit_canvas(pad)
        self._last = None
        self.refresh()
        self.show()

    # ---------- 自由摆放 ----------
    def _place_free(self, pad, gap):
        """有存过位置就用存的，没存过就自动排一排"""
        auto_x = pad
        for c, it in self._free_items:
            x, y = it.get("pos_x"), it.get("pos_y")
            if x is None or y is None:
                c.move(auto_x, pad)
                auto_x += c.width() + gap
            else:
                c.move(int(x), int(y))
            c.raise_()

    def _fit_canvas(self, pad):
        w = h = 40
        for c, _ in self._free_items:
            g = c.geometry()
            w = max(w, g.right() + pad + 1)
            h = max(h, g.bottom() + pad + 1)
        self.resize(w, h)

    def _on_card_moved(self, it, x, y):
        """拖完一张卡片：把位置写回配置（按 id 找，避免顺序错位）"""
        for data in self._cfg.get("items") or []:
            if data.get("id") == it.get("id"):
                data["pos_x"], data["pos_y"] = int(x), int(y)
                break
        bar_items.save(self._cfg)
        self._fit_canvas(max(0, int(
            (self._cfg.get("window") or {}).get("padding", 10))))

    def set_edit_mode(self, on):
        """编辑模式：每张卡片可以拖动改位置（窗口本身也能拖）"""
        self._editable = bool(on)
        for c in self._cards:
            c.set_editable(self._editable)
        self.update()

    @property
    def editable(self):
        return self._editable

    # 兼容旧调用（之前叫 apply_appearance）
    def apply_appearance(self):
        self.reload()

    # ---------- 数据 ----------
    def refresh(self):
        snap = self.state.snapshot()
        # hide_zero：数值是 0 就把整项藏起来
        for c in self._cards:
            c.setVisible(not bar_items.should_hide(c.item, snap))
        values = [bar_items.full_text(c.item, snap) for c in self._cards]
        rates = ([bar_items.format_rate(c.item, snap) for c in self._cards]
                 if any(c.item.get("show_rate") for c in self._cards) else None)
        if values == self._last:
            return
        self._last = values
        for i, c in enumerate(self._cards):
            c.set_value(values[i], rates[i] if rates else None)

    # ---------- 整体背景 ----------
    def paintEvent(self, e):
        win = self._cfg.get("window") or {}
        alpha = int(win.get("bg_alpha", 0))
        if alpha <= 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = float(win.get("radius", 14))
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self.width(), self.height()), r, r)
        c = QColor(str(win.get("bg_color") or "#000000"))
        c.setAlpha(max(0, min(255, alpha)))
        p.fillPath(path, c)
        p.end()

    # ---------- 整窗拖动 ----------
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = (e.globalPosition().toPoint()
                          - self.frameGeometry().topLeft())
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
