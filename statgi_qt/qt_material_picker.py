# -*- coding: utf-8 -*-
"""选材料对话框：搜索框 + 列表，边打边筛，上下键选，回车确认。

从 qt_bar_editor.py 拆出来的（第 4 批，纯搬运）。
`_lab` 从 qt_bar_common 借。"""

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QListWidget
import qt_theme as T
from qt_widgets import small_button
from qt_bar_common import _lab


class MaterialPicker(QDialog):
    """选材料 —— 带搜索框。

    名单可能上百条，`QInputDialog.getItem` 那种下拉列表翻起来很痛苦，
    所以这里用「搜索框 + 列表」：边打边筛，上下键选，回车确认。
    """

    def __init__(self, parent, materials, alpha=150):
        super().__init__(parent)
        self.setWindowTitle("选材料")
        self.setMinimumSize(400, 480)
        self.setStyleSheet(
            f"QDialog {{ background: {T.BG}; }}"
            f"QLabel {{ color: {T.TEXT}; background: transparent;"
            f" border: none; }}")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)
        root.addWidget(_lab(f"要盯住哪个材料？（共 {len(materials)} 个）", 13))

        self.search = QLineEdit()
        self.search.setPlaceholderText("输入关键字筛选，回车选中…")
        self.search.setFixedHeight(30)
        self.search.textChanged.connect(self._refilter)
        root.addWidget(self.search)

        self.list = QListWidget()
        self.list.setAlternatingRowColors(False)
        # ⚠ 样式表里别写 `QListWidget::item { color: ... }`（会盖掉 setForeground）
        pal = self.list.palette()
        pal.setColor(pal.ColorRole.Text, QColor(T.TEXT))
        self.list.setPalette(pal)
        self.list.setStyleSheet(f"""
            QListWidget {{
                background: rgba(0,0,0,90); border: 1px solid {T.BORDER};
                border-radius: 8px; padding: 4px; outline: none;
            }}
            QListWidget::item {{ padding: 6px 8px; border-radius: 5px; }}
            QListWidget::item:selected {{ background: {T.ACCENT}; color: #10161f; }}
        """)
        self.list.addItems(materials)
        self.list.setCurrentRow(0)
        self.list.itemDoubleClicked.connect(lambda _i: self.accept())
        root.addWidget(self.list, 1)

        self.empty = _lab("没有匹配的材料", 12, color=T.DIM)
        self.empty.hide()
        root.addWidget(self.empty)

        foot = QHBoxLayout()
        foot.addStretch(1)
        ok = small_button("选中", self.accept, alpha, kind="accent",
                          width=88, height=32)
        ok.setDefault(True)
        foot.addWidget(ok)
        foot.addWidget(small_button("取消", self.reject, alpha,
                                    width=88, height=32))
        root.addLayout(foot)

        self.search.returnPressed.connect(self._on_enter)
        self.search.setFocus()

    # ---- 内部 ----

    def _refilter(self, text):
        """边打边筛：命中的显示，其余跳过。

        注意：Qt 会把「当前项」保持在原来的行号上，所以筛完必须把
        当前项挪到第一个可见项；筛不到任何东西时要清空当前项，
        否则 chosen() 会返回上一次的那个名字。
        """
        key = (text or "").strip().lower()
        cur = self.list.currentItem()
        if cur is not None and cur.isHidden():
            self.list.setCurrentItem(None)
        first = -1
        shown = 0
        for i in range(self.list.count()):
            it = self.list.item(i)
            hit = (not key) or (key in it.text().lower())
            it.setHidden(not hit)
            if hit:
                shown += 1
                if first < 0:
                    first = i
        if shown == 0:
            self.list.setCurrentItem(None)
        elif self.list.currentItem() is None:
            self.list.setCurrentRow(first)
        self.empty.setVisible(shown == 0)

    def _on_enter(self):
        it = self.list.currentItem()
        if it is not None and not it.isHidden():
            self.accept()

    def chosen(self):
        it = self.list.currentItem()
        if it is None or it.isHidden():
            return ""
        return it.text()
