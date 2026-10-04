# -*- coding: utf-8 -*-
"""两个跟「收益细则」有关的弹窗。

   RecordEditDialog   改一条记录的名称 / 备注
   NameListDialog     配黑 / 白名单（决定"认出来了要不要记账"）

从 qt_dialogs.py 拆出来的（第 2 批，纯搬运）。

⚠ NameListDialog 跟「管理识别名单」的分工：
   names_db       决定**能不能识别**（认不出来的名字进不来）
   NameListDialog 决定**认出来了要不要记账**"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QColor
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
                               QPushButton, QWidget, QListWidget, QLineEdit,
                               QPlainTextEdit)
from qt_theme import TEXT, DIM, ACCENT, BG, BORDER, label_qss, btn_qss
from qt_dlg_card import CardDialog


class RecordEditDialog(QDialog):
    """改一条收益记录的名称 / 备注。

    名称的作用跟「选项的名字」一样（卡片标题），备注跟「选项的简介」一样。
    名称留空 = 用默认名（日期 + 起止时间 + 时长）。
    """

    def __init__(self, parent, rec, alpha=150):
        super().__init__(parent)
        self.setWindowTitle("编辑这条记录")
        self.setMinimumWidth(520)
        self.alpha = alpha
        self._rec = rec or {}

        self.setStyleSheet(f"""
            QDialog {{ background: {BG}; }}
            QLineEdit {{
                background: rgba(255,255,255,16); color: {TEXT};
                border: 1px solid {BORDER}; border-radius: 6px;
                padding: 5px 8px; selection-background-color: {ACCENT};
            }}
            QPlainTextEdit {{
                background: rgba(255,255,255,16); color: {TEXT};
                border: 1px solid {BORDER}; border-radius: 6px;
                padding: 5px 8px; selection-background-color: {ACCENT};
            }}
            QLabel {{ color: {TEXT}; background: transparent; }}
        """)

        import svc_records
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 16)
        root.setSpacing(8)

        def lab(t, dim=False):
            x = QLabel(t)
            x.setStyleSheet(label_qss(DIM if dim else TEXT, 12))
            return x

        root.addWidget(lab("名称", dim=False))
        self.name_edit = QLineEdit(svc_records.display_name(self._rec))
        self.name_edit.setPlaceholderText("留空则用默认名（日期 + 时间 + 时长）")
        root.addWidget(self.name_edit)

        root.addWidget(lab(f"默认名：{svc_records.default_name(self._rec)}", dim=True))
        root.addSpacing(4)

        root.addWidget(lab("备注", dim=False))
        self.notes_edit = QPlainTextEdit(svc_records.display_notes(self._rec))
        self.notes_edit.setPlaceholderText("随便写点什么")
        self.notes_edit.setFixedHeight(110)
        root.addWidget(self.notes_edit)

        root.addSpacing(6)
        bottom = QHBoxLayout()
        reset = QPushButton("清空名称与备注")
        reset.setFixedHeight(32)
        reset.setCursor(Qt.PointingHandCursor)
        reset.setStyleSheet(btn_qss("danger", self.alpha))
        reset.clicked.connect(self._clear)
        bottom.addWidget(reset)
        bottom.addStretch(1)
        ok = QPushButton("确定")
        ok.setFixedSize(84, 32)
        ok.setCursor(Qt.PointingHandCursor)
        ok.setStyleSheet(btn_qss("accent", self.alpha))
        ok.clicked.connect(self.accept)
        bottom.addWidget(ok)
        no = QPushButton("取消")
        no.setFixedSize(84, 32)
        no.setCursor(Qt.PointingHandCursor)
        no.setStyleSheet(btn_qss("normal", self.alpha))
        no.clicked.connect(self.reject)
        bottom.addWidget(no)
        root.addLayout(bottom)

    def _clear(self):
        self.name_edit.setText("")
        self.notes_edit.setPlainText("")

    def values(self):
        """返回 (name, notes)。名称等于默认名时也原样存下去，不改用户输入。"""
        return (self.name_edit.text().strip(),
                self.notes_edit.toPlainText().strip())


class StopSummaryDialog(CardDialog):
    """停止监测后的「本次小结」。

    只在**手动停止**时弹（退出程序不弹，见 qt_window._shutdown），
    也可以在设置里关掉（`stop_summary`）。

    内容 = 刚写进「收益细则」的那条：时长 / 摩拉 / 狗粮 / 材料（总数 + 种类数）。
    「复制」按钮把同样的内容做成纯文字放进剪贴板，方便贴到群里。

    2026-10-04 改版（用户要求）：换成卡片式（圆角 + 右上角 ✕ + 整宽按钮），
    并且**列出几个选项让用户选接下来干什么**（查看收益记录 / 查看每日收益 /
    继续监测 / 什么都不做）。选完由 `qt_window` 去执行 —— 弹窗自己不碰主窗口。
    """

    def __init__(self, parent, rec, alpha=150, title="本次监测小结"):
        super().__init__(parent, alpha=alpha, title=title or "本次监测小结")
        self._title = title or "本次监测小结"
        self.alpha = alpha
        self._rec = rec or {}

        import svc_records
        rec = self._rec
        dur = svc_records.format_duration(int(rec.get("seconds", 0) or 0))
        mora = int(rec.get("mora", 0) or 0)
        art = int(rec.get("artifact", 0) or 0)
        mats = {str(k): int(v) for k, v in (rec.get("materials") or {}).items()}
        mat_total = sum(mats.values())

        self.set_subtitle(f"{rec.get('start', '')}　→　{rec.get('end', '')}")

        # ---- 四个数字（保留原来的排法）----
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(6)
        rows = (("时长", dur),
                ("摩拉", f"+{mora:,}"),
                ("狗粮", f"+{art}"),
                ("材料", f"+{mat_total}"))
        for i, (k, v) in enumerate(rows):
            a = QLabel(k)
            a.setStyleSheet(label_qss(DIM, 13))
            b = QLabel(v)
            b.setStyleSheet(label_qss(ACCENT, 15, True))
            grid.addWidget(a, i, 0)
            grid.addWidget(b, i, 1)
        grid.setColumnStretch(2, 1)
        self.add_layout(grid)

        # ---- 材料：**只显示总数**，不列具体是哪些东西 ----
        # 用户 2026-09-29 要求：挂机常常十几个小时，材料种类能上百，
        # 把名字列出来又长又没意义 —— 只给数量（外加"多少种"让人心里有数）。
        # ⚠ 别再加回"前几名明细"。
        if mats:
            kinds = QLabel(f"共 {len(mats)} 种材料")
            kinds.setStyleSheet(label_qss(DIM, 12))
            self.add_widget(kinds)

        # ---- 让用户选接下来干什么 → **已按用户要求去掉**（2026-10-04）
        # 用户看过效果之后说：「共几种材料下面那四个选项删掉，保留确定」。
        # 所以这里只剩「复制」+「确定」；想加回来就在 `_pre` / `_opts` 里加。
        self.add_secondary("复制", self._copy)
        self.add_confirm("确定")
        self._text = self._as_text()

    def _as_text(self):
        """摊成纯文字（复制按钮 + 测试用）"""
        rec = self._rec
        mats = {str(k): int(v) for k, v in (rec.get("materials") or {}).items()}
        import svc_records
        lines = [f"【{self._title}】{rec.get('start', '')} → {rec.get('end', '')}",
                 f"时长　{svc_records.format_duration(int(rec.get('seconds', 0) or 0))}",
                 f"摩拉　+{int(rec.get('mora', 0) or 0):,}",
                 f"狗粮　+{int(rec.get('artifact', 0) or 0)}",
                 f"材料　+{sum(mats.values())}"]
        # 只报总数 + 种类数，**不列具体物品**（挂机久了种类太多，列出来没意义）
        if mats:
            lines[-1] += f"（{len(mats)} 种）"
        return "\n".join(lines)

    def _copy(self):
        try:
            QGuiApplication.clipboard().setText(self._text)
        except Exception:
            pass


class NameListDialog(QDialog):
    """配置一张黑 / 白名单：从「所有可选名字」里挑，可搜索。

    左边 = 还没选的（可搜索），右边 = 已选的。
    点一下就在两边之间搬。确定后写回设置，返回 True。

    跟「管理识别名单」那个弹窗的分工：
        names_db      决定**能不能识别**（认不出来的名字进不来）
        NameListDialog 决定**认出来了要不要记账**
    """

    def __init__(self, parent, key, title, desc, pool, chosen, alpha=150):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(720, 660)
        self.alpha = alpha
        self.key = key
        self._pool = sorted(str(x) for x in pool)
        self._chosen = [str(x) for x in (chosen or [])]

        self.setStyleSheet(f"""
            QDialog {{ background: {BG}; }}
            QLineEdit {{
                background: rgba(255,255,255,16); color: {TEXT};
                border: 1px solid {BORDER}; border-radius: 6px;
                padding: 3px 8px; selection-background-color: {ACCENT};
            }}
            QLabel {{ color: {TEXT}; background: transparent; }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 16)
        root.setSpacing(9)

        head = QLabel(title)
        head.setStyleSheet(label_qss(TEXT, 16, True))
        root.addWidget(head)

        tip = QLabel(desc)
        tip.setWordWrap(True)
        tip.setStyleSheet(label_qss(DIM, 12))
        root.addWidget(tip)

        cols = QHBoxLayout()
        cols.setSpacing(10)

        # ---- 左：可选（带搜索）----
        left = QVBoxLayout()
        left.setSpacing(6)
        lb = QLabel("可选（双击加进右边；Ctrl/Shift 多选后点「→ 加入」）")
        lb.setStyleSheet(label_qss(DIM, 12))
        left.addWidget(lb)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索名字…")
        self.search.setFixedHeight(30)
        self.search.textChanged.connect(self._refilter)
        left.addWidget(self.search)
        self.pool_list = self._make_list()
        # ⚠ 用双击而不是单击：单击要留给「选中」（多选后点按钮批量搬），
        #   两者都绑 itemClicked 的话一选就被搬走，没法多选了。
        self.pool_list.itemDoubleClicked.connect(self._add_one)
        left.addWidget(self.pool_list, 1)

        # 中间的搬运按钮
        mid = QVBoxLayout()
        mid.addStretch(1)
        for text, cb in (("→ 加入", self._add_checked),
                         ("← 移出", self._del_checked)):
            b = QPushButton(text)
            b.setFixedSize(82, 30)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(btn_qss("normal", self.alpha))
            b.clicked.connect(cb)
            mid.addWidget(b)
        mid.addStretch(1)
        cols.addLayout(left, 1)
        cols.addLayout(mid)
        # ---- 右：已选 ----
        right = QVBoxLayout()
        right.setSpacing(6)
        self.right_label = QLabel("已选（双击移出）")
        self.right_label.setStyleSheet(label_qss(DIM, 12))
        right.addWidget(self.right_label)
        spacer = QWidget()
        spacer.setFixedHeight(36)          # 跟左边的搜索框对齐
        right.addWidget(spacer)
        self.chosen_list = self._make_list()
        self.chosen_list.itemDoubleClicked.connect(self._del_one)
        right.addWidget(self.chosen_list, 1)
        cols.addLayout(right, 1)

        root.addLayout(cols, 1)

        # ---- 底部 ----
        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        for text, kind, cb in (("全选可见", "normal", self._add_all_visible),
                               ("清空名单", "danger", self._clear),
                               ("恢复原样", "normal", self._revert)):
            b = QPushButton(text)
            b.setFixedHeight(32)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(btn_qss(kind, self.alpha))
            b.clicked.connect(cb)
            bottom.addWidget(b)
        bottom.addStretch(1)
        ok = QPushButton("确定")
        ok.setFixedSize(84, 32)
        ok.setCursor(Qt.PointingHandCursor)
        ok.setStyleSheet(btn_qss("accent", self.alpha))
        ok.clicked.connect(self.accept)
        bottom.addWidget(ok)
        no = QPushButton("取消")
        no.setFixedSize(84, 32)
        no.setCursor(Qt.PointingHandCursor)
        no.setStyleSheet(btn_qss("normal", self.alpha))
        no.clicked.connect(self.reject)
        bottom.addWidget(no)
        root.addLayout(bottom)

        self._original = list(self._chosen)
        self._rebuild()

    # ---------- 内部 ----------

    def _make_list(self):
        """两个列表：点一下搬一个，Ctrl/Shift 多选后用中间按钮批量搬。

        ⚠ 不能用 NoSelection —— 那样 selectedItems() 永远为空，
        「→ 加入 / ← 移出」两个按钮就形同虚设（踩过）。
        """
        w = QListWidget()
        w.setAlternatingRowColors(False)
        w.setSelectionMode(QListWidget.ExtendedSelection)
        pal = w.palette()
        pal.setColor(pal.ColorRole.Text, QColor(TEXT))
        w.setPalette(pal)
        # ⚠ 样式表里别写 `QListWidget::item { color: ... }`
        w.setStyleSheet(f"""
            QListWidget {{
                background: rgba(0,0,0,90); border: 1px solid {BORDER};
                border-radius: 8px; padding: 4px; outline: none;
            }}
            QListWidget::item {{ padding: 5px 6px; }}
            QListWidget::item:selected {{ background: {ACCENT}; color: #10161f; }}
        """)
        return w

    def _rebuild(self):
        self._refilter(self.search.text())

    def _refilter(self, text):
        key = (text or "").strip().lower()
        chosen = set(self._chosen)
        self.pool_list.clear()
        for n in self._pool:
            if n in chosen:
                continue
            if key and key not in n.lower():
                continue
            self.pool_list.addItem(n)
        self.chosen_list.clear()
        for n in self._chosen:
            if key and key not in n.lower():
                continue
            self.chosen_list.addItem(n)
        self.right_label.setText(
            f"已选 {len(self._chosen)} 个（点一下移出）")

    def _add_one(self, item):
        """双击一条 -> 加进右边"""
        n = item.text()
        if n not in self._chosen:
            self._chosen.append(n)
            self._chosen = sorted(self._chosen)
        self._rebuild()

    def _del_one(self, item):
        """双击一条 -> 从右边移出"""
        n = item.text()
        if n in self._chosen:
            self._chosen.remove(n)
        self._rebuild()

    def _add_checked(self):
        for it in self.pool_list.selectedItems():
            n = it.text()
            if n not in self._chosen:
                self._chosen.append(n)
        self._chosen = sorted(self._chosen)
        self._rebuild()

    def _del_checked(self):
        for it in self.chosen_list.selectedItems():
            if it.text() in self._chosen:
                self._chosen.remove(it.text())
        self._rebuild()

    def _add_all_visible(self):
        for i in range(self.pool_list.count()):
            self._chosen.append(self.pool_list.item(i).text())
        self._chosen = sorted(set(self._chosen))
        self._rebuild()

    def _clear(self):
        self._chosen = []
        self._rebuild()

    def _revert(self):
        self._chosen = list(self._original)
        self._rebuild()

    def chosen(self):
        return list(self._chosen)
