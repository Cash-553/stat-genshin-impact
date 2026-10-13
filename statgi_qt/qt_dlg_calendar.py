# -*- coding: utf-8 -*-
"""深色日历选择弹窗 —— 给「额外跳过的日期」挑日期用。

用户 2026-10-12 给的参考图（深色卡片、顶部大标题写选中那天、月份行带 ‹ ›、
选中日是**强调色圆圈**、底部整宽确定）→ 这里的风格跟「退出确认」那类卡片弹窗
统一（同一个 `CardDialog` 基类）。

⚠ 为什么不让用户手输日期：手输要处理 `2026-10-01` / `2026/10/01` / `20261001`
  三种写法 + 各种非法值，体验也差。日历点一下就完事，还不会有错值。

用法：
    dlg = CalendarDialog(parent, alpha, date=某天)
    if dlg.exec() == QDialog.Accepted:
        d = dlg.selected_date()      # datetime.date
"""
import calendar
import datetime as dt

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QLabel, QMenu,
                               QPushButton, QVBoxLayout, QWidget)

import qt_theme as T
from qt_dlg_card import CardDialog
from qt_theme import ACCENT, btn_qss, label_qss, rgba
from qt_widgets import bind_cb

WEEK_CN = ("一", "二", "三", "四", "五", "六", "日")     # 周一开头（跟国内习惯一致）
# 参考图里是「日 一 二 … 六」（周日开头）。这里跟参考图一致。
WEEK_HEAD = ("日", "一", "二", "三", "四", "五", "六")


class CalendarDialog(CardDialog):
    """挑一个日期。确定后用 `selected_date()` 取。"""

    DAY_SIZE = 36          # 日期格子边长（正方形 → 圆角一半就是正圆）

    def __init__(self, parent=None, alpha=150, date=None):
        super().__init__(parent, alpha, title="选择日期", width=352)
        self._sel = date or dt.date.today()
        self._shown = self._sel.replace(day=1)
        self._day_btns = {}

        # ---------- 顶部：选中的那天（大标题） ----------
        self.head = QLabel("")
        self.head.setAlignment(Qt.AlignCenter)
        self.head.setStyleSheet(label_qss(T.TEXT, 17, True))
        self.add_widget(self.head)
        self.add_widget(self._spacer(2))

        # ---------- 月份行：2026年10月（点开选月） + ‹ › ----------
        row = QHBoxLayout()
        row.setSpacing(6)
        self.month_btn = QPushButton("")
        self.month_btn.setCursor(Qt.PointingHandCursor)
        self.month_btn.setFlat(True)
        self.month_btn.setStyleSheet(
            f"QPushButton {{ color:{T.TEXT}; background:transparent; border:none;"
            f" font-size:15px; font-weight:600; padding:2px 6px; }}"
            f"QPushButton:hover {{ color:{ACCENT}; }}")
        self.month_btn.clicked.connect(bind_cb(self._pick_month))
        row.addWidget(self.month_btn)
        row.addStretch(1)
        self.b_prev = self._nav_btn("‹", -1)
        self.b_next = self._nav_btn("›", +1)
        row.addWidget(self.b_prev)
        row.addWidget(self.b_next)
        self.add_layout(row)
        self.add_widget(self._spacer(4))

        # ---------- 星期表头 ----------
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(2)
        self.grid.setVerticalSpacing(2)
        for c, w in enumerate(WEEK_HEAD):
            lb = QLabel(w)
            lb.setAlignment(Qt.AlignCenter)
            lb.setFixedHeight(22)
            lb.setStyleSheet(label_qss(T.DIM, 11))
            self.grid.addWidget(lb, 0, c)
        self.add_widget(self.grid_host)

        # ---------- 底部 ----------
        self.add_confirm("确定")
        self.add_secondary("取消", self.reject)
        self._rebuild()
        self.fit_to_subtitle(0.85)

    # ------------------------------------------------------------ 小件
    @staticmethod
    def _spacer(h):
        w = QWidget()
        w.setFixedHeight(h)
        w.setStyleSheet("background: transparent;")
        return w

    def _nav_btn(self, text, delta):
        b = QPushButton(text)
        b.setFixedSize(30, 26)
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet(
            f"QPushButton {{ color:{T.TEXT}; background:transparent; border:none;"
            f" font-size:17px; }}"
            f"QPushButton:hover {{ color:{ACCENT}; }}")
        b.clicked.connect(bind_cb(self._shift_month, delta))
        return b

    def _day_qss(self, selected):
        if selected:
            return (f"QPushButton {{ background:{ACCENT}; color:#08222E;"
                    f" border:none; border-radius:{self.DAY_SIZE // 2}px;"
                    f" font-size:13px; font-weight:600; }}")
        return (f"QPushButton {{ background:transparent; color:{T.TEXT};"
                f" border:none; border-radius:{self.DAY_SIZE // 2}px;"
                f" font-size:13px; }}"
                f"QPushButton:hover {{ background:{rgba('#FFFFFF', 22)}; }}")

    # ------------------------------------------------------------ 构建
    def _rebuild(self):
        """按 `self._shown` 重画网格"""
        y, m = self._shown.year, self._shown.month
        self.head.setText(f"{self._sel.year}年{self._sel.month}月{self._sel.day}日"
                          f"{'周' + WEEK_HEAD[(self._sel.weekday() + 1) % 7]}")
        self.month_btn.setText(f"{y}年{m}月 ⌄")

        # 清掉旧的日期按钮（保留第 0 行的表头）
        for (_d, btn) in list(self._day_btns.items()):
            self.grid.removeWidget(btn)
            btn.setParent(None)
            try:
                btn.deleteLater()
            except Exception:
                pass
        self._day_btns = {}

        first_wd, days = calendar.monthrange(y, m)
        # `monthrange` 的 0 = 周一；表头是周日开头 → 换算
        col0 = (first_wd + 1) % 7
        r, c = 1, col0
        for d in range(1, days + 1):
            day = dt.date(y, m, d)
            b = QPushButton(str(d))
            b.setFixedSize(self.DAY_SIZE, self.DAY_SIZE)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(self._day_qss(day == self._sel))
            b.clicked.connect(bind_cb(self._choose, day))
            self.grid.addWidget(b, r, c)
            self._day_btns[d] = b
            c += 1
            if c > 6:
                c = 0
                r += 1
        # 空行也占住位置，免得窗口高度跳来跳去
        for rr in range(r, 7):
            for cc in range(7):
                if self.grid.itemAtPosition(rr, cc) is None:
                    self.grid.addWidget(self._spacer(0), rr, cc)

    # ------------------------------------------------------------ 交互
    def _choose(self, day):
        self._sel = day
        if day.month != self._shown.month or day.year != self._shown.year:
            self._shown = day.replace(day=1)
        self._rebuild()

    def _shift_month(self, delta):
        y, m = self._shown.year, self._shown.month + delta
        if m < 1:
            y, m = y - 1, 12
        elif m > 12:
            y, m = y + 1, 1
        self._shown = dt.date(y, m, 1)
        self._rebuild()

    def _pick_month(self):
        """点「2026年10月 ⌄」：列出这一年的 12 个月 + 上/下一年"""
        menu = QMenu(self)
        for mm in range(1, 13):
            act = menu.addAction(f"{self._shown.year}年{mm}月")
            if mm == self._shown.month:
                act.setEnabled(False)
            act.triggered.connect(bind_cb(self._goto_month, self._shown.year, mm))
        menu.addSeparator()
        a1 = menu.addAction(f"← {self._shown.year - 1}年")
        a1.triggered.connect(bind_cb(self._goto_month, self._shown.year - 1,
                                     self._shown.month))
        a2 = menu.addAction(f"{self._shown.year + 1}年 →")
        a2.triggered.connect(bind_cb(self._goto_month, self._shown.year + 1,
                                     self._shown.month))
        menu.exec(self.month_btn.mapToGlobal(self.month_btn.rect().bottomLeft()))

    def _goto_month(self, year, month):
        try:
            self._shown = dt.date(int(year), int(month), 1)
        except Exception:
            return
        self._rebuild()

    # ------------------------------------------------------------ 取值
    def selected_date(self):
        return self._sel

    def selected_text(self):
        return self._sel.isoformat()
