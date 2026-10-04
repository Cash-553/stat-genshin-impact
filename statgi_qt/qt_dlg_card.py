# -*- coding: utf-8 -*-
"""卡片式弹窗：圆角卡片 + 右上角 ✕ + **竖排单选** + 整宽按钮。

风格参照用户 2026-10-04 给的那张图（深蓝卡片、青色实心按钮、右上角 ✕、
单选圈、底下「不再提醒我」小方框）。
配色直接用主题里的 `CARD` / `ACCENT` —— 那张图的配色正是软件自带的
「深夜蓝 + 经典蓝」预设，所以不用另搞一套色。

为什么抽成基类：**退出确认**和**本次小结**都要长这样，两处各写一遍迟早走形。

⚠ 无边框窗口（FramelessWindowHint）→ 拖动得自己实现，不然用户挪不了窗口。
⚠ 单选竖排是用户明确要求的（那张参考图里是横排，他不要）。
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDialog, QFrame,
                               QHBoxLayout, QLabel, QPushButton, QRadioButton,
                               QVBoxLayout)

from qt_theme import (ACCENT, BORDER, CARD, DIM, FONT, TEXT, btn_qss,
                      card_qss, label_qss, rgba)
from qt_widgets import set_btn_icon


class CardDialog(QDialog):
    """一个深色圆角卡片式的弹窗。

    用法：
        dlg = CardDialog(parent, alpha, title="退出 StatGI")
        dlg.add_option("tray", "隐藏到任务栏托盘", checked=True)
        dlg.add_option("exit", "退出主程序")
        dlg.add_checkbox("不再提醒我")
        dlg.add_confirm("确定")
        if dlg.exec() == QDialog.Accepted:
            key = dlg.chosen()
    """

    def __init__(self, parent=None, alpha=150, title="", width=340):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setModal(True)
        # ⚠ 宽度别贪大：用户 2026-10-04 反馈「字都没占到一半，没必要这么宽」。
        #   所以按内容给一个**小**的最小宽度（默认 340），让布局自己撑开。
        self.setMinimumWidth(width)
        self._alpha = alpha
        self._drag = None
        self._group = QButtonGroup(self)
        self._radios = {}
        self._check = None
        self._confirm = None

        self.setStyleSheet(f"""
            QLabel {{ color: {TEXT}; background: transparent; }}
            QRadioButton {{ color: {TEXT}; font-size: 14px; spacing: 10px;
                            background: transparent; }}
            /* ⚠ 圆圈要**整数半径**才锐利，而且别太大：用户 2026-10-04 要求"改小一点"。
               width/height 是内容区，border 2px 加在外面 → 总尺寸 12+4=16px，
               半径就是 8px（正好一半，是正圆）。 */
            QRadioButton::indicator {{ width: 12px; height: 12px;
                border-radius: 8px; border: 2px solid {rgba(TEXT, 150)};
                background: transparent; }}
            QRadioButton::indicator:checked {{ border: 2px solid {TEXT};
                background: {ACCENT}; }}
            QRadioButton::indicator:hover {{ border: 2px solid {ACCENT}; }}
            QCheckBox {{ color: {TEXT}; font-size: 13px; spacing: 8px;
                         background: transparent; }}
            QCheckBox::indicator {{ width: 12px; height: 12px;
                border: 1px solid {rgba(TEXT, 130)}; border-radius: 3px;
                background: transparent; }}
            QCheckBox::indicator:checked {{ background: {ACCENT};
                border-color: {ACCENT}; }}
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.card = QFrame(self)
        self.card.setObjectName("card")
        self.card.setStyleSheet(card_qss(alpha))
        outer.addWidget(self.card)

        self.body = QVBoxLayout(self.card)
        self.body.setContentsMargins(22, 16, 22, 18)
        self.body.setSpacing(12)

        # ---- 标题行：标题 + 右上角 ✕ ----
        head = QHBoxLayout()
        head.setSpacing(8)
        self.title_label = QLabel(title or "")
        self.title_label.setStyleSheet(label_qss(TEXT, 15, True))
        head.addWidget(self.title_label)
        head.addStretch(1)
        self.close_btn = QPushButton()
        self.close_btn.setFixedSize(26, 26)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setToolTip("关闭")
        self.close_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none;"
            f" border-radius: 13px; }}"
            f"QPushButton:hover {{ background: {rgba(TEXT, 26)}; }}")
        set_btn_icon(self.close_btn, "x", 13, color=DIM)
        self.close_btn.clicked.connect(self.reject)
        head.addWidget(self.close_btn)
        self.body.addLayout(head)

        # 副标题（灰字说明）
        self.sub_label = QLabel("")
        self.sub_label.setStyleSheet(label_qss(DIM, 12))
        self.sub_label.setWordWrap(True)
        self.sub_label.hide()
        self.body.addWidget(self.sub_label)

        # ---- 自定义内容区（数字表之类，**在选项之前**）----
        # ⚠ 这一层必须在 _opts / _foot 之前建好。
        #   原来 add_widget() 直接往 body 末尾加，而按钮在更早建的 _foot 里，
        #   结果「数字跑到确定按钮下面去了」（2026-10-04 渲染截图才看出来）。
        self._pre = QVBoxLayout()
        self._pre.setSpacing(8)
        self.body.addLayout(self._pre)

        # ---- 单选区（**竖排**）----
        self._opts = QVBoxLayout()
        self._opts.setSpacing(11)
        self.body.addLayout(self._opts)

        # ---- 复选框 + 整宽按钮 ----
        self._foot = QVBoxLayout()
        self._foot.setSpacing(10)
        self.body.addLayout(self._foot)

    # ------------------------------------------------------------ 组装
    def set_subtitle(self, text):
        self.sub_label.setText(str(text))
        self.sub_label.setVisible(bool(text))

    def add_widget(self, w, stretch=0):
        """往卡片里塞自定义内容（比如本次小结那几个数字）。

        位置在**选项之前**、副标题之后。
        """
        self._pre.addWidget(w, stretch)
        return w

    def add_layout(self, lay):
        """同上，加一个布局"""
        self._pre.addLayout(lay)
        return lay

    def fit_to_subtitle(self, ratio=0.85):
        """把窗口宽度收窄到**副标题占一行宽度的 ratio**。

        用户 2026-10-04 的要求：「还是不够窄，至少让『隐藏到托盘后监测会继续
        在后台运行』在这一行占到 85%」。所以不写死宽度 —— 量出来再反推。
        """
        text = self.sub_label.text()
        if not text:
            return
        f = QFont(FONT)
        f.setPixelSize(12)                       # 跟 label_qss(..., 12) 对齐
        fm = QFontMetrics(f)
        # ⚠ 必须**按行取最大**：`horizontalAdvance` 碰到多行文字会把各行宽度
        #   加起来（两行 30 字 → 算成 478px），窗口就会宽一倍
        #   （2026-10-04 渲染「正在下载」时发现的，609px）。
        lines = [ln for ln in str(text).split("\n")] or [""]
        need = max(fm.horizontalAdvance(ln) for ln in lines)
        margins = 22 + 22                        # card 的左右内边距
        w = int(need / max(0.3, float(ratio))) + margins + 2
        self.setMinimumWidth(max(240, w))

    def add_option(self, key, text, checked=False, tip=""):
        """加一个竖排单选"""
        b = QRadioButton(str(text))
        b.setCursor(Qt.PointingHandCursor)
        if tip:
            b.setToolTip(str(tip))
        self._group.addButton(b)
        self._radios[str(key)] = b
        self._opts.addWidget(b)
        if checked or len(self._radios) == 1:
            b.setChecked(True)
        return b

    def add_checkbox(self, text, checked=False, boxed=True):
        """加一个复选框（默认放在一个细边框的小方框里，跟参考图一致）"""
        cb = QCheckBox(str(text))
        cb.setCursor(Qt.PointingHandCursor)
        cb.setChecked(bool(checked))
        self._check = cb
        if boxed:
            holder = QFrame()
            holder.setStyleSheet(
                f"QFrame {{ border: 1px solid {rgba(TEXT, 45)};"
                f" border-radius: 8px; }}")
            lay = QHBoxLayout(holder)
            lay.setContentsMargins(12, 8, 12, 8)
            lay.addWidget(cb)
            lay.addStretch(1)
            self._foot.addWidget(holder)
        else:
            self._foot.addWidget(cb)
        return cb

    def add_confirm(self, text="确定", action=None):
        """整宽的强调色按钮（默认点了=确定；传 action 可以改成别的，比如取消）"""
        b = QPushButton(str(text))
        b.setFixedHeight(40)
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet(btn_qss("accent", self._alpha))
        b.clicked.connect(action if action is not None else self.accept)
        self._foot.addWidget(b)
        self._confirm = b
        return b

    def add_progress(self, show=True):
        """进度条（下载/更新这种要显示百分比的场景）"""
        from PySide6.QtWidgets import QProgressBar
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setFixedHeight(18)
        bar.setTextVisible(True)
        bar.setStyleSheet(
            f"QProgressBar {{ background:{rgba('#FFFFFF', 20)}; border:none;"
            f" border-radius:9px; text-align:center; color:{TEXT};"
            f" font-size:11px; }}"
            f"QProgressBar::chunk {{ background:{ACCENT}; border-radius:9px; }}")
        bar.setValue(0)
        bar.setVisible(bool(show))
        self._pre.addWidget(bar)
        self.progress = bar
        return bar

    def add_secondary(self, text, callback=None):
        """一个小的次要按钮（左对齐，放在整宽按钮上面）"""
        b = QPushButton(str(text))
        b.setFixedHeight(30)
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet(btn_qss("normal", self._alpha))
        if callback is not None:
            b.clicked.connect(callback)
        row = QHBoxLayout()
        row.addWidget(b)
        row.addStretch(1)
        self._foot.addLayout(row)
        return b

    # ------------------------------------------------------------ 取值
    def chosen(self):
        """选中的选项 key（没选返回 None）"""
        for key, b in self._radios.items():
            if b.isChecked():
                return key
        return None

    def set_chosen(self, key):
        b = self._radios.get(str(key))
        if b is not None:
            b.setChecked(True)

    def check_checked(self):
        return bool(self._check is not None and self._check.isChecked())

    # ------------------------------------------------------------ 无边框拖动
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag is not None and (e.buttons() & Qt.LeftButton):
            self.move(e.globalPosition().toPoint() - self._drag)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._drag = None
        super().mouseReleaseEvent(e)


class ExitDialog(CardDialog):
    """点 ✕ 时的确认窗（用户 2026-10-04 要求改成这个风格）。

    · 两个选项**竖排**：隐藏到任务栏托盘 / 退出主程序
    · 「不再提醒我」勾上 → 把选择写进 `close_behavior`，以后不再问
      （设置里「点右上角 ✕ 时」那一项还是能改回来）
    """

    def __init__(self, parent=None, alpha=150, default="tray"):
        super().__init__(parent, alpha, title="退出 StatGI", width=300)
        self.set_subtitle("隐藏到托盘后，监测会继续在后台运行。")
        self.add_option("tray", "隐藏到任务栏托盘", checked=(default != "exit"),
                        tip="窗口收起来，程序继续跑，挂机不中断")
        self.add_option("exit", "退出主程序", checked=(default == "exit"),
                        tip="保存数据并彻底关闭")
        # ⚠ 复选框**不要外面那个方框**（用户 2026-10-04 明确要求）
        self.add_checkbox("不再提醒我", checked=False, boxed=False)
        self.add_confirm("确定")
        # 再收窄：让那句说明占满一行宽度的 ~85%
        self.fit_to_subtitle(0.85)
