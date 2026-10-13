# -*- coding: utf-8 -*-
"""模块开关卡片"滚动置顶" —— **通用机制**（用户 2026-10-13 要求）。

效果（每个模块各自独立判断）：
    · 模块的开关卡片还在画面里      → 不钉 ✗
    · 开关滚出画面、而它的选项还在  → 把**那张真卡片**原样钉在页面顶部 ✓
    · 另一个模块的选项进入画面      → 钉住的换成它 ✓（前一个自动放回原位）
    · 往回滚、开关又回到画面        → 取消钉住 ✓
    · 同时只钉一个 ✓

怎么做：把**真卡片**临时搬进一个贴在视口顶部的浮层（原位置塞一个同高的透明
占位块，这样下面的内容不会跳），滚回去再搬回原位。
    —— 因为是"真卡片搬家"而不是画一张假的，所以长相、开关、点击全都天然一致 ✓
       （用户要求：一模一样、不做区分、开关能点 ✓）

⚠ **通用性**：这个类不认任何具体模块。谁把 (卡片, 选项区) 交进来，谁就有置顶 ✓。
   新加模块 → 模块界面自己交回来 → 自动生效，**不需要改这个文件** ✓。
"""

from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtWidgets import QWidget

try:
    from qt_theme import CARD as _CARD, RADIUS_CARD as _RADIUS
    from qt_theme import card_qss as _card_qss
except Exception:            # 拿不到就退回纯色
    _CARD, _RADIUS = "#1f2025", 12

    def _card_qss(alpha=None, radius=12):
        return ""

__all__ = ["StickyCardHeader"]


class _Layer(QWidget):
    """钉住时卡片待的浮层（贴在视口顶部，不随内容滚动）。"""

    def __init__(self, scroll):
        super().__init__(scroll.viewport())
        self._scroll = scroll
        self.setStyleSheet("background: transparent;")

    def wheelEvent(self, e):        # 鼠标停在钉住的卡片上也要能滚页面
        try:
            self._scroll.wheelEvent(e)
        except Exception:
            e.ignore()


class StickyCardHeader:
    """把模块的开关卡片"钉"在滚动区顶部。

    Args:
        scroll: 那个 QScrollArea
        pairs_provider: 返回 [(卡片控件, 该模块的选项区控件), ...] 的函数
                        （每次刷新都重新问，所以模块增删/显隐都能跟上 ✓）
    """

    def __init__(self, scroll, pairs_provider):
        self.scroll = scroll
        self.provider = pairs_provider
        self._pinned = None                 # 当前钉住的那张卡片
        self._home = None                   # 它原来的 (布局, 下标, 占位块)
        self._layer = _Layer(scroll)
        self._layer.setVisible(False)
        # 浮层底色 = 卡片底色（不透明）→ 钉住时不透出下面的内容 ✓
        try:
            self._layer.setStyleSheet(f"background: {_CARD};")
        except Exception:
            pass
        try:
            sb = scroll.verticalScrollBar()
            # ⚠ 别写不存在的方法名（写过 _on_any，结果被 try 吞了、滚动没反应）
            sb.valueChanged.connect(lambda *_: self.update())
            sb.rangeChanged.connect(lambda *_: self.update())
        except Exception:
            pass
        # 布局变化（显隐模块）不会触发滚动信号，补一个轻量定时器兜底
        self._timer = QTimer(scroll)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.update)
        self._timer.start()

    # ---------------- 外部只需调这个 ----------------
    def update(self, *_a):
        try:
            if not self.scroll.isVisible():
                return
        except Exception:
            pass
        vp = self.scroll.viewport()
        pairs = [(r, b) for (r, b) in self._pairs()
                 if r is not None and self._ok(r) and (b is None or self._ok(b))]
        target = None
        for i, (row, box) in enumerate(pairs):
            try:
                # 判断"这张卡片的原位还在不在画面里"：
                #   · 已经钉住的 → 用它原位留下的**占位块**判断（卡片本身在浮层里，
                #     坐标已经没有意义了；之前就是漏了这点 → 钉住后再也放不回去 ✗）
                #   · 没钉住的   → 直接看它自己
                if row is self._pinned and self._home and self._home[2] is not None:
                    anchor = self._home[2]
                else:
                    anchor = row
                if anchor.mapTo(vp, QPoint(0, anchor.height())).y() > 0:
                    continue                  # 原位还在画面里 → 不钉/放回 ✓
                # 这个模块的"地盘"到哪结束：下一个模块卡片的顶边
                limit = 10 ** 7
                nxt = None
                for row2, _b2 in pairs[i + 1:]:
                    y2 = row2.mapTo(vp, QPoint(0, 0)).y()
                    if y2 > 0:
                        nxt = y2
                        break
                if nxt is not None:
                    limit = nxt
                elif box is not None and self._ok(box) and box.height() > 0:
                    limit = min(limit, box.mapTo(vp, QPoint(0, box.height())).y())
                if limit > 0:
                    target = row
            except Exception:
                continue
        if target is self._pinned:
            self._resize_layer()
            return
        self._unpin()
        if target is not None:
            self._pin(target)

    @staticmethod
    def _ok(w):
        try:
            return bool(w is not None and w.isVisible() and w.height() > 0)
        except Exception:
            return False

    def refresh(self, *_a):
        self.update()

    # ---------------- 内部 ----------------
    def _pairs(self):
        try:
            return list(self.provider() or [])
        except Exception:
            return []

    def _solid_row(self, row):
        """把卡片临时改成**完全不透明**（其余卡片保持原样）"""
        self._row_style = row.styleSheet()
        try:
            # 外圈那条灰边换成高亮白（用户要求）；底色仍然不透明
            row.setStyleSheet(
                f"QFrame#card {{ background: {_CARD};"
                f" border: 2px solid #ffffff;"
                f" border-radius: {_RADIUS}px; }}")
        except Exception:
            pass

    def _restore_row(self, row):
        try:
            row.setStyleSheet(getattr(self, "_row_style", "") or "")
        except Exception:
            pass

    def _ref_geom(self, row):
        """量一张**没被钉住的兄弟卡片**的位置/宽度，用来对齐（拿不到就退回估算）"""
        vp = self.scroll.viewport()
        for r, _b in self._pairs():
            try:
                if r is None or r is row or r is self._pinned:
                    continue
                if not r.isVisible() or r.width() < 100:
                    continue
                pt = r.mapTo(vp, QPoint(0, 0))
                return pt.x(), r.width()
            except Exception:
                continue
        return 5, max(120, vp.width() - 10)

    def _resize_layer(self):
        try:
            _x, _w = self._ref_geom(self._pinned)
            self._layer.resize(_w, self._layer.height())
            self._layer.move(_x, 0)
            if self._pinned is not None:
                self._pinned.setGeometry(0, 0, _w, self._pinned.height())
        except Exception:
            pass

    def _pin(self, row):
        try:
            parent = row.parentWidget()
            lay = parent.layout()
            idx = lay.indexOf(row) if lay is not None else -1
            spacer = None
            if lay is not None and idx >= 0:
                spacer = QWidget(parent)
                spacer.setStyleSheet("background: transparent;")
                spacer.setFixedHeight(row.height())
                lay.insertWidget(idx, spacer)
            self._home = (lay, idx, spacer)
            # 钉住的那张换成"完全不透明"（其余卡片保持原样）
            self._solid_row(row)
            row.setParent(self._layer)
            # 位置/宽度**照兄弟卡片**摆（自对齐 ✓，别再硬算内边距 ✗）
            _x, _w = self._ref_geom(row)
            self._layer.resize(_w, row.height())
            self._layer.move(_x, 0)
            row.setGeometry(0, 0, _w, row.height())
            row.show()
            self._layer.show()
            self._layer.raise_()
            self._pinned = row
        except Exception:
            self._pinned = None

    def _unpin(self):
        row, home = self._pinned, self._home
        self._pinned, self._home = None, None
        try:
            self._layer.setVisible(False)
        except Exception:
            pass
        if row is not None:
            self._restore_row(row)
        if row is None or home is None:
            return
        lay, idx, spacer = home
        try:
            if spacer is not None and lay is not None:
                lay.removeWidget(spacer)
                spacer.deleteLater()
            if lay is not None:
                row.setParent(lay.parentWidget())
                if 0 <= idx <= lay.count():
                    lay.insertWidget(idx, row)
                else:
                    lay.addWidget(row)
                row.show()
        except Exception:
            pass
