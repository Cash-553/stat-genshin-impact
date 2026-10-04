# -*- coding: utf-8 -*-
"""更新下载界面：下载动画图标 + 公告/名言轮播 + 底部进度条 + 右下速度。

用户 2026-10-04 定的版式：

    ┌──────────────────────────────────────────────┐
    │  正在更新到 0.9.5                          ✕ │
    │                                              │
    │   (↓ 动画)   更新公告：…                      │  ← 图标在左，文字在右
    │   [大图标]   名言：正文 / 空一行 / 右下署名     │
    │                                              │
    │  ▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░      │  ← 进度条在**底部**（整宽）
    │                    65.9 MB/s · 39% · 48/121 MB │ ← 信息在**进度条右下**
    │  [              取消更新                    ] │
    └──────────────────────────────────────────────┘

关于图标：用户 2026-10-04 说了**不要 morphicons**（那是 JS 变形引擎，图标也只能
从它内部调），**从项目自带的 61 个矢量图标里挑**。所以用 `rotate-ccw`
（单个圆箭头，跟用户草图上那个"缺口圆圈"一致）在转，下完换成自带的 `check`。
"""
import time
from collections import deque

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                               QProgressBar, QSizePolicy, QVBoxLayout, QWidget)

import qt_theme as T
from qt_dlg_card import CardDialog
from qt_icon import draw_subs
from qt_icon_data import ICONS
from qt_theme import ACCENT, DIM, TEXT, label_qss, rgba


class SpinIcon(QWidget):
    """更新动画：**项目自带图标**在转；下完变自带的对勾。

    ⚠ 用户 2026-10-04 明确：**不要用 morphicons**（那是 JS 变形引擎，
      图标也只能从它内部调），从项目自带的 61 个矢量图标里挑。
      所以这里用 `qt_icon_data.ICONS` 里的 `rotate-ccw`（单个圆箭头，
      跟用户草图上那个"缺口圆圈"一致），下完换成自带的 `check`。
    """

    def __init__(self, parent=None, icon="rotate-ccw", size=96,
                 interval=30, step=6.0, color=None):
        super().__init__(parent)
        self._icon_name = icon
        self._subs = ICONS.get(icon)
        self._size = int(size)
        self._step = float(step)
        self._color = QColor(color or ACCENT)
        self._angle = 0.0
        self._done = False
        self._pop = 0.0
        self.setFixedSize(self._size, self._size)
        self._timer = QTimer(self)
        self._timer.setInterval(int(interval))
        self._timer.timeout.connect(self._tick)

    # ---------- 对外 ----------
    def set_icon_size(self, px):
        px = max(16, int(px))
        if px != self._size:
            self._size = px
            self.setFixedSize(px, px)
            self.update()

    def icon_size(self):
        return self._size

    def icon_name(self):
        return self._icon_name

    def angle(self):
        return self._angle

    def set_done(self, done=True):
        """下载完了 → 换成对勾（带一个"弹一下"的小动画）"""
        self._done = bool(done)
        self._pop = 0.0
        self.update()

    def is_done(self):
        return self._done

    # ---------- 动画 ----------
    def showEvent(self, e):
        super().showEvent(e)
        self._timer.start()

    def hideEvent(self, e):
        self._timer.stop()
        super().hideEvent(e)

    def _tick(self):
        if self._done:
            if self._pop < 1.0:
                self._pop = min(1.0, self._pop + 0.12)
                self.update()
            return
        self._angle = (self._angle + self._step) % 360.0
        self.update()

    @staticmethod
    def _smooth(t):
        t = max(0.0, min(1.0, t))
        return t * t * (3.0 - 2.0 * t)

    # ---------- 画 ----------
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        side = float(min(self.width(), self.height()))
        base = self._size * 0.92
        # ⚠ 笔画宽就传 2.0（跟 `IconWidget` 的默认值一致）——
        #   `draw_subs` 内部会乘 `base / 24`，外面再乘一次的话
        #   线条会粗 4 倍（107px 的图标变成 35px 粗的一坨，真踩过）。
        if self._done:
            # 对勾：0.7 → 1.05 → 1.0 弹一下
            k = self._pop
            scale = 0.7 + 0.35 * self._smooth(min(1.0, k * 1.6)) \
                - 0.05 * max(0.0, k - 0.6) / 0.4
            p.save()
            p.translate(side / 2.0, side / 2.0)
            p.scale(max(0.2, scale), max(0.2, scale))
            p.translate(-side / 2.0, -side / 2.0)
            draw_subs(p, ICONS.get("check"), side, base, color=self._color)
            p.restore()
            return
        draw_subs(p, self._subs, side, base, angle=self._angle,
                  color=self._color)


class FadeTicker(QWidget):
    """公告 / 名言轮播：渐显 → 停一会儿 → 渐淡 → 换下一条。

    显示时长（用户 2026-10-04 最终口径）：**公告 5 秒、名言 5 秒**，
    每条各自带 `hold`，不写就用默认值。

    条目是 dict：
        {"head": 小标题(可空，空就不显示), "body": 正文,
         "by": 署名(可空，会右对齐并自动加「—— 」), "hold": 显示毫秒}

    ⚠ 名言按用户要求**不显示标题**，并且正文和署名之间**空一行**。
    """

    HOLD_MS = 5000
    FADE_MS = 420
    GAP_MS = 240
    MAX_LINES = 3

    def __init__(self, parent=None, height=112):
        super().__init__(parent)
        self._items = []
        self._idx = -1
        self.setFixedHeight(int(height))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        self.head = QLabel("")
        self.head.setStyleSheet(label_qss(ACCENT, 12, True))
        v.addWidget(self.head)
        self.body = QLabel("")
        self.body.setWordWrap(True)
        self.body.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.body.setStyleSheet(label_qss(T.TEXT, 13))
        v.addWidget(self.body, 1)
        # 署名：单独一行、右对齐（正文和它之间空一行 = 上面的 spacing + 这里再顶一点）
        self.by = QLabel("")
        self.by.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.by.setStyleSheet(label_qss(DIM, 12))
        v.addWidget(self.by)

        self._eff = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._eff)
        self._eff.setOpacity(0.0)
        self._anim = QPropertyAnimation(self._eff, b"opacity", self)
        self._anim.setDuration(self.FADE_MS)
        self._anim.setEasingCurve(QEasingCurve.InOutQuad)
        self._anim.finished.connect(self._on_anim_done)

        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.timeout.connect(self._on_hold)

    # ---------- 数据 ----------
    @classmethod
    def clip_text(cls, text, max_lines=None):
        """正文截断：最多 max_lines 行，多出来的换成"…"（不然会压到底部进度条）"""
        lines = [ln for ln in str(text or "").split("\n")]
        n = int(max_lines or cls.MAX_LINES)
        if len(lines) <= n:
            return str(text or "").strip()
        return "\n".join(lines[:n]).rstrip() + " …"

    def set_items(self, items, start=True):
        out = []
        for it in (items or []):
            if not isinstance(it, dict):
                continue
            body = str(it.get("body", "") or "").strip()
            if not body:
                continue
            out.append({
                "head": str(it.get("head", "") or "").strip(),
                "body": self.clip_text(body),
                "by": str(it.get("by", "") or "").strip(),
                "hold": int(it.get("hold") or self.HOLD_MS),
            })
        self._items = out or [{"head": "", "body": "更新进行中，请稍候…",
                               "by": "", "hold": self.HOLD_MS}]
        self._idx = -1
        if start:
            self.next_item()

    def count(self):
        return len(self._items)

    def current(self):
        if 0 <= self._idx < len(self._items):
            return self._items[self._idx]
        return {"head": "", "body": "", "by": "", "hold": self.HOLD_MS}

    def opacity(self):
        return float(self._eff.opacity())

    # ---------- 轮播 ----------
    def next_item(self):
        if not self._items:
            return
        self._idx = (self._idx + 1) % len(self._items)
        it = self.current()
        self.head.setText(it["head"])
        self.head.setVisible(bool(it["head"]))     # 名言没有标题 → 整行藏起来
        self.body.setText(it["body"])
        # 署名：空一行（body 是拉伸的，天然留白）+ 右下角 + 自动加「—— 」
        self.by.setText(f"—— {it['by']}" if it["by"] else "")
        self.by.setVisible(bool(it["by"]))
        self._fade_in()

    def _fade_in(self):
        self._anim.stop()
        self._anim.setStartValue(self._eff.opacity())
        self._anim.setEndValue(1.0)
        self._anim.start()

    def _fade_out(self):
        self._anim.stop()
        self._anim.setStartValue(self._eff.opacity())
        self._anim.setEndValue(0.0)
        self._anim.start()

    def _on_anim_done(self):
        """亮着 → 该淡出了；已经空了 → 该换下一条"""
        if self._eff.opacity() < 0.02:
            self._hold.start(self.GAP_MS)
        else:
            self._hold.start(int(self.current().get("hold") or self.HOLD_MS))

    def _on_hold(self):
        if self._eff.opacity() < 0.02:
            self.next_item()
        else:
            self._fade_out()

    def stop(self):
        self._anim.stop()
        self._hold.stop()


class UpdateProgressDialog(CardDialog):
    """下载/更新时的界面（版式见模块开头的图）。"""

    ICON_RATIO = 0.25        # 图标占弹窗宽度（用户：三分之一或四分之一）
    ICON_MIN = 56
    ICON_MAX = 150

    def __init__(self, parent=None, alpha=150, ver="", size=0, notes=""):
        super().__init__(parent, alpha, title=f"正在更新到 {ver}", width=430)
        self._total = int(size or 0)
        self._samples = deque(maxlen=24)
        self._speed = 0.0

        # ---------- 上面一行：左边图标，右边公告/名言 ----------
        top = QHBoxLayout()
        top.setSpacing(16)
        self.icon = SpinIcon(self, icon="rotate-ccw", size=96)
        self._fit_icon()
        top.addWidget(self.icon, 0, Qt.AlignTop)

        from quotes import pick
        items = []
        if str(notes or "").strip():
            # 用户 2026-10-04 改的口径：公告也是 5 秒（原来 10 秒）
            items.append({"head": "更新公告", "body": str(notes).strip(),
                          "hold": 5_000})
        for body, by in pick(6):
            items.append({"head": "", "body": body, "by": by, "hold": 5_000})
        self.ticker = FadeTicker(self, height=112)
        self.ticker.set_items(items)
        top.addWidget(self.ticker, 1)
        self.add_layout(top)

        # ---------- 底部：整宽进度条 ----------
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(16)
        self.bar.setStyleSheet(
            f"QProgressBar {{ background:{rgba('#FFFFFF', 18)}; border:none;"
            f" border-radius:8px; }}"
            f"QProgressBar::chunk {{ background:{ACCENT}; border-radius:8px; }}")
        self.add_widget(self.bar)

        # ---------- 进度条右下方：速度 / 百分比 / 已下载 ----------
        info = QHBoxLayout()
        info.addStretch(1)
        self.speed = QLabel("正在连接…")
        self.speed.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.speed.setStyleSheet(label_qss(DIM, 12))
        info.addWidget(self.speed)
        self.add_layout(info)

        self.add_confirm("取消更新", action=self.reject)
        self.fit_to_subtitle(0.85)

    # ---------- 尺寸 ----------
    def _fit_icon(self):
        try:
            px = int(self.width() * self.ICON_RATIO)
            px = max(self.ICON_MIN, min(self.ICON_MAX, px))
            self.icon.set_icon_size(px)
        except Exception:
            pass

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit_icon()

    # ---------- 进度 ----------
    def set_progress(self, done, total=0):
        now = time.time()
        done = int(done or 0)
        total = int(total or self._total or 0)
        self._samples.append((now, done))
        while len(self._samples) > 2 and now - self._samples[0][0] > 3.0:
            self._samples.popleft()
        if len(self._samples) >= 2:
            t0, d0 = self._samples[0]
            dt = max(0.001, now - t0)
            inst = max(0.0, (done - d0) / dt)
            self._speed = inst if self._speed <= 0 else (self._speed * 0.6 + inst * 0.4)
        if total > 0:
            pct = max(0, min(100, int(done * 100 / total)))
            self.bar.setValue(pct)
            self.speed.setText(
                f"{self._speed / 1024 / 1024:.1f} MB/s　·　{pct}%　"
                f"{done / 1024 / 1024:.0f} / {total / 1024 / 1024:.0f} MB")
        else:
            self.speed.setText(f"{self._speed / 1024 / 1024:.1f} MB/s　·　"
                               f"{done / 1024 / 1024:.1f} MB")

    def set_status(self, text):
        self.speed.setText(str(text))

    def accept(self):
        self.ticker.stop()
        super().accept()

    def reject(self):
        self.ticker.stop()
        super().reject()
