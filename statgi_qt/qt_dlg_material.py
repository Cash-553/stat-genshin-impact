# -*- coding: utf-8 -*-
"""材料名单弹窗：搜索 / 只看自动登记 / 勾选删除 / 双击改名 / 添加。

从 qt_dialogs.py 拆出来的（第 2 批，纯搬运）。
入口在「设置 → 开发 → 材料库 → 材料名单 [编辑…]」。"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QMessageBox, QListWidget, QListWidgetItem, QLineEdit,
                               QCheckBox)
from qt_theme import TEXT, DIM, ACCENT, BG, BORDER, label_qss, btn_qss
import svc_capture


class MaterialDialog(QDialog):
    """管理识别名单 —— 决定"认得出什么"。

    名单存在 ``data/names.json``（第一次运行时从 ``generated_names.py`` 拷一份），
    所以能改、能恢复默认。

    ⚠ 名单里的名字才会被统计。**全删光了就什么都识别不到** ——
      所以上面有红字警告、右下角有「恢复默认名单」。

    改名：双击列表里那一行直接改。
    """

    def __init__(self, parent, alpha=150):
        super().__init__(parent)
        self.setWindowTitle("管理识别名单")
        self.setMinimumSize(680, 700)
        self.alpha = alpha

        import svc_names
        self.db = svc_names
        self._names = []

        # 对话框自己有背景，不然会跟着系统主题走 ——
        # 浅色系统下会变成白底黑字，跟整个应用完全不搭（应用没有全局调色板）
        self.setStyleSheet(f"""
            QDialog {{ background: {BG}; }}
            QLineEdit {{
                background: rgba(255,255,255,16); color: {TEXT};
                border: 1px solid {BORDER}; border-radius: 6px;
                padding: 3px 8px; selection-background-color: {ACCENT};
            }}
            QCheckBox {{ color: {DIM}; spacing: 7px; }}
            QCheckBox::indicator {{
                width: 14px; height: 14px; border-radius: 3px;
                border: 1px solid rgba(255,255,255,70); background: transparent;
            }}
            QCheckBox::indicator:checked {{
                background: {ACCENT}; border: 1px solid {ACCENT};
            }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 16)
        root.setSpacing(9)

        # 红字警告
        warn = QLabel("⚠ 名单决定可识别的物品范围。不在名单中的名称不会被统计；"
                      "若名单被清空，将无法识别任何物品，请用下方「恢复默认名单」还原。")
        warn.setWordWrap(True)
        warn.setStyleSheet(label_qss("#E06C5A", 12, True))
        root.addWidget(warn)

        self.tip = QLabel("")
        self.tip.setStyleSheet(label_qss(DIM, 12))
        root.addWidget(self.tip)

        # ---- 搜索 + 筛选 ----
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索名字…")
        self.search.setFixedHeight(30)
        self.search.textChanged.connect(self._rebuild)
        bar.addWidget(self.search, 1)

        self.only_extra = QCheckBox("只看自己加的")
        self.only_extra.setToolTip("隐藏内置默认名单里的那些，只看你增删过的")
        self.only_extra.toggled.connect(self._rebuild)
        bar.addWidget(self.only_extra)

        self.only_used = QCheckBox("只看记录里出现过的")
        self.only_used.setToolTip("只看收益记录里真的识别到过的名字（找漏记用）")
        self.only_used.toggled.connect(self._rebuild)
        bar.addWidget(self.only_used)
        root.addLayout(bar)

        # ---- 列表 ----
        self.list = QListWidget()
        self.list.setAlternatingRowColors(False)
        # ⚠ 样式表里**不能**写 `QListWidget::item { color: ... }`，
        #   那样会盖掉 QListWidgetItem.setForeground()，按类型上色全失效。
        pal = self.list.palette()
        pal.setColor(pal.ColorRole.Text, QColor(TEXT))
        self.list.setPalette(pal)
        self.list.setStyleSheet(f"""
            QListWidget {{
                background: rgba(0,0,0,90); border: 1px solid {BORDER};
                border-radius: 8px; padding: 4px; outline: none;
            }}
            QListWidget::item {{ padding: 5px 6px; }}
            QListWidget::item:selected {{ background: {ACCENT}; color: #10161f; }}
            QListWidget::indicator {{
                width: 13px; height: 13px; border-radius: 3px;
                border: 1px solid rgba(255,255,255,70); background: transparent;
            }}
            QListWidget::indicator:checked {{
                background: {ACCENT}; border: 1px solid {ACCENT};
            }}
        """)
        self.list.itemChanged.connect(self._on_item_changed)
        root.addWidget(self.list, 1)

        # ---- 添加 ----
        add = QHBoxLayout()
        add.setSpacing(8)
        self.new_edit = QLineEdit()
        self.new_edit.setPlaceholderText("输入新名字，回车添加（材料进材料名单，其余进圣遗物名单）…")
        self.new_edit.setFixedHeight(30)
        self.new_edit.returnPressed.connect(self._on_add)
        add.addWidget(self.new_edit, 1)
        self.add_btn = QPushButton("添加")
        self.add_btn.setFixedSize(76, 30)
        self.add_btn.setCursor(Qt.PointingHandCursor)
        self.add_btn.setStyleSheet(btn_qss("accent", self.alpha))
        self.add_btn.clicked.connect(self._on_add)
        add.addWidget(self.add_btn)
        root.addLayout(add)

        # ---- 底部按钮 ----
        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        for text, kind, cb in (
                ("全选", "normal", lambda: self._check_all(True)),
                ("全不选", "normal", lambda: self._check_all(False)),
                ("删除选中", "danger", self._on_delete)):
            b = QPushButton(text)
            b.setFixedHeight(32)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(btn_qss(kind, self.alpha))
            b.clicked.connect(cb)
            bottom.addWidget(b)
        bottom.addStretch(1)
        rst = QPushButton("恢复默认名单")
        rst.setFixedHeight(32)
        rst.setCursor(Qt.PointingHandCursor)
        rst.setStyleSheet(btn_qss("danger", self.alpha))
        rst.clicked.connect(self._on_reset)
        bottom.addWidget(rst)
        close = QPushButton("关闭")
        close.setFixedSize(84, 32)
        close.setCursor(Qt.PointingHandCursor)
        close.setStyleSheet(btn_qss("normal", self.alpha))
        close.clicked.connect(self.accept)
        bottom.addWidget(close)
        root.addLayout(bottom)

        self._rebuild()

    # ---------- 数据 ----------

    def _data(self):
        try:
            return self.db.load()
        except Exception:
            return {"materials": [], "artifacts": []}

    def _builtin(self):
        """内置默认名单（判断某个名字是不是"自己加的"）"""
        try:
            return svc_names.builtin_names()
        except Exception:
            return set()

    def _used(self):
        """收益记录里真的识别到过的名字 -> 次数"""
        try:
            import svc_records
            out = {}
            for r in svc_records.load_sessions():
                for k, v in (r.get("materials", {}) or {}).items():
                    out[str(k)] = out.get(str(k), 0) + int(v or 0)
            return out
        except Exception:
            return {}

    # ---------- 列表 ----------

    def _rebuild(self):
        kw = self.search.text().strip()
        d = self._data()
        builtin = self._builtin()
        used = self._used() if self.only_used.isChecked() else {}

        # 行 = (名字, 类别, 是不是自己加的, 有没有在记录里出现过)
        rows = []
        for n in d["materials"]:
            rows.append((n, "材料", n not in builtin, used.get(n, 0)))
        for n in d["artifacts"]:
            rows.append((n, "圣遗物", n not in builtin, used.get(n, 0)))

        self.list.blockSignals(True)
        self.list.clear()
        self._names = []
        n_extra = 0
        for name, kind, extra, cnt in rows:
            if extra:
                n_extra += 1
            if self.only_extra.isChecked() and not extra:
                continue
            if self.only_used.isChecked() and not cnt:
                continue
            if kw and kw not in name:
                continue
            tag = kind + ("　自加" if extra else "")
            if cnt:
                tag += f"　记录×{cnt}"
            it = QListWidgetItem(f"{name}　　{tag}")
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEditable)
            it.setCheckState(Qt.Unchecked)
            it.setData(Qt.UserRole, name)          # 原始名字（改名时对比）
            it.setData(Qt.UserRole + 1, kind)      # 材料 / 圣遗物
            if extra:
                it.setForeground(QColor(ACCENT))   # 蓝：自己加的
            elif cnt:
                it.setForeground(QColor(TEXT))
            else:
                it.setForeground(QColor(DIM))      # 灰：内置且没用到过
            self.list.addItem(it)
            self._names.append(name)
        self.list.blockSignals(False)

        self.tip.setText(
            f"材料 {len(d['materials'])} 个　圣遗物 {len(d['artifacts'])} 个"
            f"　其中自己加的 {n_extra} 个"
            f"　·　双击可改名；没识别到过的名字显示为灰色")
        self.setWindowTitle(f"管理识别名单　共 {len(rows)} 个")

    def _check_all(self, on):
        self.list.blockSignals(True)
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(Qt.Checked if on else Qt.Unchecked)
        self.list.blockSignals(False)

    def _checked(self):
        out = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.checkState() == Qt.Checked:
                out.append((str(it.data(Qt.UserRole)),
                            str(it.data(Qt.UserRole + 1))))
        return out

    # ---------- 增删改 ----------

    def _on_item_changed(self, item):
        """改名：双击编辑完走这里（勾选框变化也走，但名字没变就跳过）"""
        old = str(item.data(Qt.UserRole))
        kind = str(item.data(Qt.UserRole + 1))
        new = item.text().strip()
        if "　　" in new:
            new = new.split("　　")[0].strip()
        if not new or new == old:
            return
        d = self._data()
        bucket = "materials" if kind == "材料" else "artifacts"
        if new in d["materials"] or new in d["artifacts"]:
            QMessageBox.warning(self, "重名", f"名单里已经有「{new}」了。")
            self._rebuild()
            return
        try:
            d[bucket][d[bucket].index(old)] = new
            self.db.save(d)
        except ValueError:
            pass
        self._rebuild()

    def _on_add(self):
        name = self.new_edit.text().strip()
        if not name:
            return
        d = self._data()
        if name in d["materials"] or name in d["artifacts"]:
            QMessageBox.warning(self, "已存在", f"名单里已经有「{name}」了。")
            return
        # 判断该进哪一份：能当成圣遗物的进圣遗物，其余的进材料
        is_art = svc_capture.is_artifact_name(name)
        d["artifacts" if is_art else "materials"].append(name)
        self.db.save(d)
        self.new_edit.clear()
        self._rebuild()
        self.list.scrollToBottom()

    def _on_delete(self):
        rows = self._checked()
        if not rows:
            QMessageBox.information(self, "提示", "先勾选要删除的名字。")
            return
        d = self._data()
        left = len(d["materials"]) + len(d["artifacts"]) - len(rows)
        msg = (f"要从名单里删除这 {len(rows)} 个名字吗？\n\n"
               f"删掉之后识别到它们就**不会记账**了")
        if left <= 0:
            msg = ("⚠ 这样会把名单删空，之后**什么都不会被统计**！\n\n"
                   "确定要删吗？（关掉这个窗口后可以点「恢复默认名单」还原）")
        if QMessageBox.question(self, "确认删除", msg) != QMessageBox.Yes:
            return
        drop = {n for n, _ in rows}
        d["materials"] = [n for n in d["materials"] if n not in drop]
        d["artifacts"] = [n for n in d["artifacts"] if n not in drop]
        self.db.save(d)
        self._rebuild()

    def _on_reset(self):
        if QMessageBox.question(
                self, "恢复默认名单",
                "会把识别名单还原成内置的那份。\n\n"
                "你自己加过或删过的名字都会没掉。确定吗？") != QMessageBox.Yes:
            return
        self.db.reset_to_default()
        self._rebuild()
