# -*- coding: utf-8 -*-
"""通用的「勾选列表」控件 —— 单选 / 多选都走它（用户 2026-10-13 要求）。

为什么单独做：用户要的是**通用效果** —— 「连续执行配置组」「到点自动开始监测」
「指定配置组结束后停止监测」都用它，而且**以后新模块只要有勾选需求，直接用这个
控件就自动长得一样**（选中是强调色 ✓），不用各自写一遍。

用法：
    from qt_checklist import CheckList
    lst = CheckList(parent, alpha, mode="multi"|"single", on_change=self._xxx)
    lst.set_items(["开门", "狗粮"], chosen=["开门"])   # 重建
    lst.values()      # 多选 → ["开门", ...]（按 BGI 顺序）
    lst.value()       # 单选 → "开门"（没选返回 ""）

单选模式：勾一个会自动取消其他的；再点一次可以取消（= 不指定）✓
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QVBoxLayout, QWidget

try:
    from qt_theme import ACCENT as _ACCENT
    from qt_theme import label_qss as _label_qss
except Exception:                       # 拿不到主题就退回默认
    _ACCENT = "#4C9AFF"

    def _label_qss(color=None, size=12):
        return ""


def _box_qss(accent):
    """勾选框样式：**选中用强调色**（用户要求；连续执行那边也一样）"""
    return f"""
    QCheckBox {{
        color: #dcdde1;
        font-size: 13px;
        spacing: 8px;
        padding: 2px 0;
    }}
    QCheckBox::indicator {{
        width: 15px;
        height: 15px;
        border-radius: 4px;
        border: 1px solid #55585f;
        background: transparent;
    }}
    QCheckBox::indicator:hover {{
        border: 1px solid {accent};
    }}
    QCheckBox::indicator:checked {{
        background: {accent};
        border: 1px solid {accent};
    }}
    """


class CheckList(QWidget):
    def __init__(self, parent=None, alpha=1.0, mode="multi", on_change=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        self.mode = mode
        self.alpha = alpha
        self.on_change = on_change
        self.boxes = []                 # [(名字, QCheckBox), ...]
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(4)
        self._names = []

    # ---------- 建 / 重建 ----------
    def set_items(self, names, chosen=None):
        chosen = list(chosen or [])
        self._names = list(names)
        while self._lay.count():
            it = self._lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                try:
                    w.deleteLater()
                except Exception:
                    pass
        self.boxes = []
        for n in self._names:
            box = QCheckBox(n)
            box.setStyleSheet(_box_qss(_ACCENT))
            box.setChecked(n in chosen)
            box.toggled.connect(lambda _c, name=n: self._toggled(name))
            self._lay.addWidget(box)
            self.boxes.append((n, box))
        # 多选模式：勾选顺序不重要；单选模式：保证最多一个
        if self.mode == "single":
            self._enforce_single()
        # ⚠ 换完内容必须通知 Qt 重算高度，否则放进折叠卡里高度塌成 22px、
        #   点开看不到任何选项（用户 2026-10-13 反馈"点开没有选项"就是这个）✗
        try:
            self.updateGeometry()
            h = 0
            for _n, b in self.boxes:
                h += max(20, b.sizeHint().height()) + 4
            self.setMinimumHeight(max(24, h + 4))
        except Exception:
            pass

    def sizeHint(self):
        """按内容报高度 —— 不加这个，放进折叠卡里高度会塌成 22px（点开看不到选项 ✗）"""
        try:
            from PySide6.QtCore import QSize
            h = 0
            for _n, b in self.boxes:
                h += max(20, b.sizeHint().height()) + 4
            return QSize(200, max(24, h + 4))
        except Exception:
            return super().sizeHint()

    def minimumSizeHint(self):
        return self.sizeHint()

    # ---------- 取值 ----------
    def values(self):
        return [n for (n, b) in self.boxes if b.isChecked()]

    def value(self):
        v = self.values()
        return v[0] if v else ""

    def set_value(self, name):
        for n, b in self.boxes:
            b.blockSignals(True)
            b.setChecked(bool(name) and n == name)
            b.blockSignals(False)

    def set_values(self, names):
        names = list(names or [])
        for n, b in self.boxes:
            b.blockSignals(True)
            b.setChecked(n in names)
            b.blockSignals(False)

    # ---------- 内部 ----------
    def _enforce_single(self):
        on = [n for (n, b) in self.boxes if b.isChecked()]
        if len(on) > 1:                 # 只保留最后一个被勾上的
            keep = getattr(self, "_last", on[-1])
            for n, b in self.boxes:
                if b.isChecked() and n != keep:
                    b.blockSignals(True)
                    b.setChecked(False)
                    b.blockSignals(False)

    def _toggled(self, name):
        if self.mode == "single":
            self._last = name
            self._enforce_single()
        if callable(self.on_change):
            try:
                self.on_change()
            except Exception:
                pass
