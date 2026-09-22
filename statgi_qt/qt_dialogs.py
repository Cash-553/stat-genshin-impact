# -*- coding: utf-8 -*-
"""StatGI Qt 版 · 两个弹窗：图标管理、区域框选

都是 QDialog，跟主程序一个配色。弹窗是**有系统标题栏**的
（Qt 的 QDialog 在 Windows 上很规矩，不需要像 Tk 那样自己画标题条）。
"""
import os

from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QGuiApplication, QPainter, QColor, QPen, QPixmap
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
                               QLabel, QPushButton, QFileDialog, QMessageBox,
                               QWidget, QFrame, QListWidget, QListWidgetItem,
                               QLineEdit, QCheckBox, QComboBox, QSlider,
                               QPlainTextEdit, QScrollArea)

import config_manager
import paths
from qt_theme import (TEXT, DIM, ACCENT, CARD, BG, BORDER, panel_alpha, label_qss,
                      btn_qss, combo_qss, slider_qss)
from qt_widgets import Card, set_btn_icon
from qt_icon import IconWidget

ICONS_DIR = paths.icons_dir()

SLOTS = [("slot1", "摩拉"), ("slot2", "材料"), ("slot3", "狗粮")]


def builtin_name(key):
    """内置图标文件名（打包自带，不该被覆盖）"""
    return f"_bar_{key}.png"


def custom_name(key):
    """自定义图标文件名（换图/截图都写这个，不动内置那份）"""
    return f"_bar_my_{key}.png"


# ============================================================
#  图标管理
# ============================================================
class IconManagerDialog(QDialog):
    def __init__(self, parent, on_change=None):
        super().__init__(parent)
        self.setWindowTitle("统计条图标管理")
        self.setFixedSize(720, 500)
        self.on_change = on_change
        self._photos = []

        self.settings = config_manager.load_settings()
        self.alpha = panel_alpha(self.settings)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 16)
        root.setSpacing(10)

        tip = QLabel("管理直播间收益统计条 3 个格子显示的图标，与识别无关。")
        tip.setStyleSheet(label_qss(DIM, 13))
        root.addWidget(tip)

        grid = QGridLayout()
        grid.setSpacing(10)
        self.previews = {}
        self.states = {}
        for i, (key, name) in enumerate(SLOTS):
            card = self._make_slot_card(key, name)
            grid.addWidget(card, i // 2, i % 2)
        grid.addWidget(self._make_reset_card(), 1, 1)
        root.addLayout(grid, 1)

        bottom = Card(self, alpha=self.alpha)
        bl = QHBoxLayout(bottom)
        bl.setContentsMargins(16, 12, 16, 12)
        bl.addWidget(QLabel("提示：图标文件放在 icons 文件夹，可随时更换。"))
        bl.itemAt(0).widget().setStyleSheet(label_qss(DIM, 12))
        bl.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.setFixedSize(90, 34)
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.setStyleSheet(btn_qss("normal", self.alpha))
        close_btn.clicked.connect(self.accept)
        bl.addWidget(close_btn)
        root.addWidget(bottom)

        self._refresh()

    def _make_slot_card(self, key, name):
        card = Card(self, alpha=self.alpha)
        card.setFixedHeight(150)
        lay = QHBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(12)

        box = QFrame()
        box.setFixedSize(84, 84)
        box.setStyleSheet("background: rgba(255,255,255,20); border-radius:12px;")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        pv = QLabel()
        pv.setAlignment(Qt.AlignCenter)
        bl.addWidget(pv)
        self.previews[key] = pv
        lay.addWidget(box)

        right = QVBoxLayout()
        right.setSpacing(4)
        t = QLabel(name)
        t.setStyleSheet(label_qss(TEXT, 16, True))
        st = QLabel("")
        st.setStyleSheet(label_qss(DIM, 12))
        self.states[key] = st
        right.addWidget(t)
        right.addWidget(st)
        row = QHBoxLayout()
        row.setSpacing(6)
        b1 = set_btn_icon(QPushButton("截取"), "camera", 14)
        b2 = QPushButton("更换")
        for b, kind, cb in ((b1, "normal", lambda _=False, k=key, n=name: self.on_capture(k, n)),
                            (b2, "accent", lambda _=False, k=key, n=name: self.on_replace(k, n))):
            b.setFixedHeight(30)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(btn_qss(kind, self.alpha))
            b.clicked.connect(cb)
            row.addWidget(b)
        right.addLayout(row)
        right.addStretch(1)
        lay.addLayout(right, 1)
        return card

    def _make_reset_card(self):
        card = Card(self, alpha=self.alpha)
        card.setFixedHeight(150)
        v = QVBoxLayout(card)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(4)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title_row.addWidget(IconWidget(card, name="rotate-ccw", size=18, role="TEXT"))
        t = QLabel("全部重置")
        t.setStyleSheet(label_qss(TEXT, 16, True))
        title_row.addWidget(t)
        title_row.addStretch(1)
        d = QLabel("把三个格子都恢复成程序内置的图标，\n并删掉你自己换的那些。")
        d.setStyleSheet(label_qss(DIM, 12))
        v.addLayout(title_row)
        v.addWidget(d)
        v.addStretch(1)
        b = QPushButton("重置为内置图标")
        b.setFixedHeight(32)
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet(btn_qss("normal", self.alpha))
        b.clicked.connect(self.on_reset)
        v.addWidget(b)
        return card

    # ---------- 刷新 ----------
    def _refresh(self):
        self.settings = config_manager.load_settings()
        bar = self.settings.get("stat_bar") or {}
        for key, _name in SLOTS:
            fname = bar.get(key)
            f = ICONS_DIR / fname if fname else None
            pv = self.previews[key]
            st = self.states[key]
            if f and f.exists():
                pm = QPixmap(str(f))
                if not pm.isNull():
                    self._photos.append(pm)
                    pv.setPixmap(pm.scaled(70, 70, Qt.KeepAspectRatio,
                                           Qt.SmoothTransformation))
                    pv.setText("")
                    custom = (fname == custom_name(key))
                    st.setText("自定义图标" if custom else "内置图标")
                    st.setStyleSheet(label_qss(ACCENT if custom else DIM, 12))
                    continue
            pv.setPixmap(QPixmap())
            pv.setText("未设置")
            pv.setStyleSheet(label_qss(DIM, 12))
            st.setText("文件丢失")
            st.setStyleSheet(label_qss("#E06C5A", 12))

    def _save_slot(self, key, fname):
        self.settings = config_manager.load_settings()
        bar = dict(self.settings.get("stat_bar") or {})
        bar[key] = fname
        self.settings["stat_bar"] = bar
        config_manager.save_settings(self.settings)
        self._refresh()
        if self.on_change:
            self.on_change()

    def _write_icon(self, key, img):
        ICONS_DIR.mkdir(parents=True, exist_ok=True)
        fname = custom_name(key)
        img.save(str(ICONS_DIR / fname), format="PNG")
        self._save_slot(key, fname)

    def on_capture(self, key, name):
        QMessageBox.information(
            self, "截取提示",
            f"接下来框选【{name}】的图标。\n\n· 框得越贴近图标越好\n"
            "· 看不到框选界面请按 Esc 取消")
        from qt_dialogs import select_region
        rect = select_region(self)
        if rect is None:
            return
        try:
            from capture import ScreenCapture
            cap = ScreenCapture()
            frame = cap.grab({"x": rect.x(), "y": rect.y(),
                              "w": rect.width(), "h": rect.height()})
            cap.close()
            from PIL import Image as PILImage
            img = PILImage.fromarray(frame[:, :, :3][:, :, ::-1])
            self._write_icon(key, _auto_trim(img))
            QMessageBox.information(self, "成功", f"「{name}」图标已保存！")
        except Exception as e:
            QMessageBox.warning(self, "失败", f"截取失败：{e}")

    def on_replace(self, key, name):
        p, _ = QFileDialog.getOpenFileName(
            self, f"选择「{name}」图标的图片", "",
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not p:
            return
        try:
            from PIL import Image as PILImage
            img = PILImage.open(p).convert("RGBA")
            self._write_icon(key, _auto_trim(img))
            QMessageBox.information(self, "成功", f"「{name}」图标已更新！")
        except Exception as e:
            QMessageBox.warning(self, "失败", f"保存失败：{e}")

    def on_reset(self):
        if QMessageBox.question(self, "确认重置",
                                "要把 3 个格子都恢复成内置图标吗？\n"
                                "（你自己换的图标文件会被删掉）") != QMessageBox.Yes:
            return
        removed = 0
        for key, _n in SLOTS:
            f = ICONS_DIR / custom_name(key)
            if f.exists():
                try:
                    f.unlink()
                    removed += 1
                except Exception:
                    pass
            self._save_slot(key, builtin_name(key))
        missing = [n for k, n in SLOTS if not (ICONS_DIR / builtin_name(k)).exists()]
        if missing:
            QMessageBox.warning(self, "重置完成（有缺文件）",
                                "已恢复内置图标，但这些内置文件找不到：\n  "
                                + "、".join(missing))
        else:
            QMessageBox.information(self, "重置完成",
                                    f"已恢复内置图标，删掉了 {removed} 个自定义图标。")


def _auto_trim(img, margin=4):
    """自动去掉图标四周的纯色边框"""
    try:
        import numpy as np
        a = np.array(img.convert("RGB"))
        h, w = a.shape[:2]
        if h < 20 or w < 20:
            return img
        corner = a[0, 0].astype(int)
        diff = np.abs(a.astype(int) - corner).sum(axis=2)
        ys, xs = np.where(diff > 30)
        if len(xs) == 0:
            return img
        return img.crop((max(0, int(xs.min()) - margin), max(0, int(ys.min()) - margin),
                         min(w, int(xs.max()) + margin + 1),
                         min(h, int(ys.max()) + margin + 1)))
    except Exception:
        return img


# ============================================================
#  区域框选（全屏半透明遮罩，拖一个框）
# ============================================================
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

        import names_db
        self.db = names_db
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
            import generated_names as g
            return set(g.MATERIAL_NAMES) | set(g.ARTIFACT_NAMES)
        except Exception:
            return set()

    def _used(self):
        """收益记录里真的识别到过的名字 -> 次数"""
        try:
            import sessions
            out = {}
            for r in sessions.load_sessions():
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
        try:
            import detector
            is_art = detector.Detector._is_artifact_name(
                detector.Detector.__new__(detector.Detector), name)
        except Exception:
            is_art = False
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


class BarStyleDialog(QDialog):
    """桌面悬浮窗的样式编辑 —— 像绘画软件那样**选一个框再改它的属性**。

    左边挑样式（内置的「经典」「直播间」不能改，要改先复制）；
    中间挑**改哪个框**：「全部（一起改）」改所有框共用的那份，
    选中某一格就只改那一格（写进 overrides，不影响别人）。

    改完立刻存盘 + 刷新悬浮窗。
    """

    def __init__(self, parent, alpha=150, on_apply=None):
        super().__init__(parent)
        self.setWindowTitle("桌面悬浮窗样式")
        self.setMinimumSize(900, 660)
        self.alpha = alpha
        self._on_apply = on_apply
        self._cur = None            # 当前样式名
        self._scope = self.db.SCOPE_ALL if hasattr(self, "db") else "__all__"
        self._loading = False

        import bar_styles
        self.db = bar_styles
        self._scope = bar_styles.SCOPE_ALL
        self._data = {}             # 当前样式的工作副本

        self.setStyleSheet(f"""
            QDialog {{ background: {BG}; }}
            QLabel {{ color: {TEXT}; }}
            QCheckBox {{ color: {DIM}; spacing: 7px; }}
            QCheckBox::indicator {{
                width: 14px; height: 14px; border-radius: 3px;
                border: 1px solid rgba(255,255,255,70); background: transparent;
            }}
            QCheckBox::indicator:checked {{ background: {ACCENT}; border: 1px solid {ACCENT}; }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 16)
        root.setSpacing(10)

        body = QHBoxLayout()
        body.setSpacing(12)

        # ---- 左：样式列表 ----
        left = QVBoxLayout()
        left.setSpacing(6)
        left.addWidget(self._h("样式"))
        self.list = QListWidget()
        self.list.setFixedWidth(168)
        self._style_list_qss(self.list)
        self.list.currentItemChanged.connect(self._on_pick)
        left.addWidget(self.list, 1)
        for text, kind, cb in (
                ("新建…", "accent", self._on_new),
                ("复制一份", "normal", self._on_dup),
                ("重命名…", "normal", self._on_rename),
                ("删除", "danger", self._on_delete)):
            b = QPushButton(text)
            b.setFixedHeight(28)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(btn_qss(kind, self.alpha))
            b.clicked.connect(cb)
            left.addWidget(b)
        body.addLayout(left)

        # ---- 中：改哪个框 ----
        mid = QVBoxLayout()
        mid.setSpacing(6)
        mid.addWidget(self._h("改哪个框"))
        self.scope_list = QListWidget()
        self.scope_list.setFixedWidth(120)
        self._style_list_qss(self.scope_list)
        self.scope_list.currentItemChanged.connect(self._on_scope)
        mid.addWidget(self.scope_list, 1)
        body.addLayout(mid)

        # ---- 右：参数 + 预览 ----
        right = QVBoxLayout()
        right.setSpacing(8)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }")
        holder = QWidget()
        holder.setStyleSheet("background: transparent;")
        flay = QVBoxLayout(holder)
        flay.setContentsMargins(0, 0, 8, 0)
        flay.setSpacing(5)

        self.fields = {}
        self.field_meta = {}
        for key, label, desc, kind, arg, scope in self.db.FIELDS:
            row = QHBoxLayout()
            row.setSpacing(8)
            t = QLabel(label)
            t.setStyleSheet(label_qss(TEXT, 13))
            t.setFixedWidth(88)
            row.addWidget(t)
            d = QLabel(desc)
            d.setStyleSheet(label_qss(DIM, 11))
            d.setFixedWidth(190)
            row.addWidget(d)
            w = self._make_widget(key, kind, arg)
            self.field_meta[key] = (scope, kind, arg, label)
            self.fields[key] = w
            if kind == "text":
                w.setFixedWidth(150)
                row.addWidget(w)
            elif kind in ("choice",):
                w.setFixedWidth(140)
                row.addWidget(w)
            elif kind in ("color", "color_opt"):
                w.setMinimumWidth(126)
                row.addWidget(w)
            else:
                w.setFixedWidth(140)
                row.addWidget(w)
                w._val_label = QLabel("")
                w._val_label.setFixedWidth(44)
                w._val_label.setStyleSheet(label_qss(ACCENT, 12))
                row.addWidget(w._val_label)
            row.addStretch(1)
            flay.addLayout(row)
        flay.addStretch(1)
        scroll.setWidget(holder)
        right.addWidget(scroll, 1)

        right.addWidget(self._h("预览"))
        pvbox = Card(self, alpha=self.alpha)
        pvl = QVBoxLayout(pvbox)
        pvl.setContentsMargins(12, 10, 12, 10)
        self.preview = _BarPreview(pvbox)
        pvl.addWidget(self.preview, alignment=Qt.AlignCenter)
        right.addWidget(pvbox)
        body.addLayout(right, 1)
        root.addLayout(body, 1)

        bottom = QHBoxLayout()
        self.tip = QLabel("")
        self.tip.setStyleSheet(label_qss(DIM, 12))
        bottom.addWidget(self.tip, 1)
        close = QPushButton("关闭")
        close.setFixedSize(84, 32)
        close.setCursor(Qt.PointingHandCursor)
        close.setStyleSheet(btn_qss("normal", self.alpha))
        close.clicked.connect(self.accept)
        bottom.addWidget(close)
        root.addLayout(bottom)

        self._reload_list()

    # ---------- 小工具 ----------
    def _h(self, text):
        lb = QLabel(text)
        lb.setStyleSheet(label_qss(TEXT, 14, True))
        return lb

    def _style_list_qss(self, w):
        pal = w.palette()
        pal.setColor(pal.ColorRole.Text, QColor(TEXT))
        w.setPalette(pal)
        w.setStyleSheet(f"""
            QListWidget {{
                background: rgba(0,0,0,90); border: 1px solid {BORDER};
                border-radius: 8px; padding: 4px; outline: none;
            }}
            QListWidget::item {{ padding: 6px 8px; }}
            QListWidget::item:selected {{ background: {ACCENT}; color: #10161f; }}
        """)

    def _make_widget(self, key, kind, arg):
        if kind == "choice":
            w = QComboBox()
            w.addItems([n for n, _ in arg])
            w.setStyleSheet(combo_qss())
            w.currentTextChanged.connect(lambda _t, k=key: self._on_change(k))
        elif kind == "bool":
            w = QCheckBox()
            w.toggled.connect(lambda _v, k=key: self._on_change(k))
        elif kind in ("color", "color_opt"):
            w = QPushButton("选颜色")
            w.setFixedHeight(26)
            w.setCursor(Qt.PointingHandCursor)
            w.clicked.connect(lambda _c=False, k=key: self._on_pick_color(k))
        elif kind == "text":
            w = QLineEdit()
            w.setFixedHeight(26)
            w.setStyleSheet(
                f"QLineEdit {{ background: rgba(255,255,255,16); color: {TEXT};"
                f" border: 1px solid {BORDER}; border-radius: 6px; padding: 2px 6px; }}")
            w.textChanged.connect(lambda _t, k=key: self._on_change(k))
        else:
            lo, hi = arg
            w = QSlider(Qt.Horizontal)
            w.setRange(lo, hi)
            w.setStyleSheet(slider_qss())
            w.valueChanged.connect(lambda _v, k=key: self._on_change(k))
        return w

    # ---------- 列表 ----------
    def _reload_list(self, select=None):
        self.list.blockSignals(True)
        self.list.clear()
        want = select or self.db.current()
        for name in self.db.names():
            tag = "（内置）" if self.db.is_builtin(name) else ""
            it = QListWidgetItem(f"{name}{tag}")
            it.setData(Qt.UserRole, name)
            if self.db.is_builtin(name):
                it.setForeground(QColor(DIM))
            self.list.addItem(it)
            if name == want:
                self.list.setCurrentItem(it)
        self.list.blockSignals(False)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self._on_pick(self.list.currentItem())

    def _reload_scopes(self):
        self.scope_list.blockSignals(True)
        self.scope_list.clear()
        for key in [self.db.SCOPE_ALL] + list(self.db.SLOT_KEYS):
            it = QListWidgetItem(self.db.SCOPE_LABEL[key])
            it.setData(Qt.UserRole, key)
            if key != self.db.SCOPE_ALL:
                ov = (self._data.get("overrides") or {}).get(key) or {}
                if ov:
                    it.setForeground(QColor(ACCENT))     # 蓝：这格改过
            self.scope_list.addItem(it)
            if key == self._scope:
                self.scope_list.setCurrentItem(it)
        self.scope_list.blockSignals(False)
        if self.scope_list.currentItem() is None and self.scope_list.count():
            self.scope_list.setCurrentRow(0)

    def _on_pick(self, item):
        if item is None:
            return
        self._cur = str(item.data(Qt.UserRole))
        self._data = self.db._fill(self.db.get(self._cur))
        self._scope = self.db.SCOPE_ALL
        self._reload_scopes()
        self._load()

    def _on_scope(self, item):
        if item is None:
            return
        self._scope = str(item.data(Qt.UserRole))
        self._load()

    # ---------- 读 / 写 ----------
    def _value_of(self, key):
        """当前 scope 下这个字段显示什么值"""
        scope, kind, arg, label = self.field_meta[key]
        if scope == "all":
            return self._data.get(key)
        if self._scope == self.db.SCOPE_ALL:
            return self._data.get(key)
        ov = (self._data.get("overrides") or {}).get(self._scope) or {}
        # 覆盖里没有就显示全局值（灰色提示"跟随全局"）
        return ov.get(key, self._data.get(key))

    def _is_overridden(self, key):
        scope = self.field_meta[key][0]
        if scope == "all" or self._scope == self.db.SCOPE_ALL:
            return False
        ov = (self._data.get("overrides") or {}).get(self._scope) or {}
        return key in ov

    def _load(self):
        self._loading = True
        builtin = self.db.is_builtin(self._cur)
        for key, w in self.fields.items():
            scope, kind, arg, label = self.field_meta[key]
            # 全局项在"选中某一格"时不可改（它是共用的）
            editable = (not builtin) and (scope == "slot" or self._scope == self.db.SCOPE_ALL)
            w.setEnabled(editable)
            v = self._value_of(key)
            if kind == "choice":
                w.setCurrentText({val: n for n, val in arg}.get(str(v), arg[0][0]))
            elif kind == "bool":
                w.setChecked(bool(v))
            elif kind in ("color", "color_opt"):
                c = str(v or "")
                w.setText(c or ("跟随主题" if kind == "color_opt" else "选颜色"))
                w.setStyleSheet(
                    btn_qss("normal", self.alpha) +
                    (f"QPushButton {{ background:{c}; color:#ffffff; }}" if c else ""))
            elif kind == "text":
                if w.text() != str(v or ""):
                    w.setText(str(v or ""))
            else:
                w.blockSignals(True)
                w.setValue(int(v))
                w.blockSignals(False)
                w._val_label.setText(str(int(v)))
        # 提示现在改的是谁
        who = self.db.SCOPE_LABEL.get(self._scope, self._scope)
        extra = ""
        if self._scope != self.db.SCOPE_ALL:
            extra = "　（该格单独改过的地方会用蓝色标出来）"
        tip = f"当前编辑：{self._cur}　·　改哪个框：{who}{extra}"
        if builtin:
            tip += "　·　内置样式不能改，要改请先「复制一份」"
        self.tip.setText(tip)
        self.preview.set_style(self._data)
        self._loading = False

    def _collect_into(self, key, value):
        """把某个字段写进工作副本（全局 or 该格的覆盖）"""
        scope = self.field_meta[key][0]
        if scope == "all" or self._scope == self.db.SCOPE_ALL:
            self._data[key] = value
        else:
            ov = dict(self._data.get("overrides") or {})
            d = dict(ov.get(self._scope) or {})
            base = self._data.get(key)
            if value == base:
                d.pop(key, None)          # 跟全局一样就不必单独存
            else:
                d[key] = value
            if d:
                ov[self._scope] = d
            else:
                ov.pop(self._scope, None)
            self._data["overrides"] = ov

    def _on_change(self, key):
        if self._loading or self._cur is None:
            return
        w = self.fields[key]
        scope, kind, arg, label = self.field_meta[key]
        if kind == "choice":
            v = {n: val for n, val in arg}.get(w.currentText(), arg[0][1])
        elif kind == "bool":
            v = bool(w.isChecked())
        elif kind in ("color", "color_opt"):
            txt = w.text().strip()
            v = "" if txt in ("跟随主题", "选颜色", "") else txt
        elif kind == "text":
            v = w.text()
        else:
            v = int(w.value())
            w._val_label.setText(str(v))
        self._collect_into(key, v)
        self.preview.set_style(self._data)
        if not self.db.is_builtin(self._cur):
            self.db.save_style(self._cur, self._data)
            self._reload_scopes()
            self._apply_current()

    def _on_pick_color(self, key):
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QColorDialog
        if self.db.is_builtin(self._cur):
            return
        w = self.fields[key]
        cur = w.text().strip()
        init = QColor(cur) if cur not in ("跟随主题", "选颜色", "") else QColor("#141418")
        col = QColorDialog.getColor(init, self, "选择颜色")
        if not col.isValid():
            return
        w.setText(col.name())
        self._on_change(key)

    def _apply_current(self):
        self.db.set_current(self._cur)
        if callable(self._on_apply):
            self._on_apply()

    # ---------- 增删改 ----------
    def _ask_name(self, title, default=""):
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, title, "样式名称：", text=default)
        return name.strip() if ok else ""

    def _on_new(self):
        name = self._ask_name("新建样式", "我的样式")
        if not name:
            return
        if name in self.db.all_styles():
            QMessageBox.warning(self, "重名", f"已经有叫「{name}」的样式了。")
            return
        self.db.save_style(name, self.db.CLASSIC)
        self.db.set_current(name)
        self._reload_list(select=name)
        self._apply_current()

    def _on_dup(self):
        if not self._cur:
            return
        name = self._ask_name("复制样式", f"{self._cur} 副本")
        if not name:
            return
        if name in self.db.all_styles():
            QMessageBox.warning(self, "重名", f"已经有叫「{name}」的样式了。")
            return
        self.db.save_style(name, self.db.get(self._cur))
        self.db.set_current(name)
        self._reload_list(select=name)
        self._apply_current()

    def _on_rename(self):
        if not self._cur or self.db.is_builtin(self._cur):
            QMessageBox.information(self, "提示", "内置样式不能改名。")
            return
        name = self._ask_name("重命名", self._cur)
        if not name:
            return
        if not self.db.rename_style(self._cur, name):
            QMessageBox.warning(self, "失败", "改名没成功（重名了？）。")
            return
        self._reload_list(select=name)
        self._apply_current()

    def _on_delete(self):
        if not self._cur or self.db.is_builtin(self._cur):
            QMessageBox.information(self, "提示", "内置样式不能删除。")
            return
        if QMessageBox.question(
                self, "确认删除",
                f"要删掉样式「{self._cur}」吗？") != QMessageBox.Yes:
            return
        self.db.delete_style(self._cur)
        self._reload_list()
        self._apply_current()


class _BarPreview(QWidget):
    """悬浮窗预览：按样式摆格子，数字是假的。

    固定放满 4 格（含「监测时间」）—— 这样调样式时每一格都能看到，
    也知道开了第 4 格会长什么样。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._slots = {}
        self._lay = None
        self._kind = None
        self.setMinimumSize(400, 220)

    def set_style(self, st):
        keys = ("slot1", "slot2", "slot3", "slot4")
        kind = str(st.get("layout", "row"))
        if kind != self._kind:
            if self._lay is not None:
                while self._lay.count():
                    it = self._lay.takeAt(0)
                    w = it.widget()
                    if w is not None:
                        w.setParent(None)
                old = self.layout()
                if old is not None:
                    QWidget().setLayout(old)
            self._kind = kind
            if kind == "grid":
                lay = QGridLayout(self)
                for i, k in enumerate(keys):
                    lay.addWidget(self._slot(k), i // 2, i % 2)
            else:
                lay = QVBoxLayout(self) if kind == "column" else QHBoxLayout(self)
                for k in keys:
                    lay.addWidget(self._slot(k))
            self._lay = lay
        m = max(0, int(st.get("spacing", 8)))
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(m)
        for s in self._slots.values():
            s.setVisible(True)
            s.apply_style(st)
        self.adjustSize()

    def _slot(self, key):
        import bar_styles
        import qt_bar
        import paths
        s = self._slots.get(key)
        if s is None:
            s = qt_bar.Slot(self, bar_styles.SLOT_NAMES.get(key, ""), key)
            s.set_count({"slot1": "143,610", "slot2": "6,188",
                         "slot3": "222", "slot4": "10:38:24"}[key])
            icon = paths.icons_dir() / f"_bar_{key}.png"
            s.set_icon_file(icon if icon.exists() else None)
            self._slots[key] = s
        return s


class RegionSelector(QWidget):
    def __init__(self, parent=None):
        super().__init__(None)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                            | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setCursor(Qt.CrossCursor)
        self._start = None
        self._cur = None
        self._done = False
        self._result = None

        # 盖住所有屏幕
        rect = QRect()
        for s in QGuiApplication.screens():
            rect = rect.united(s.geometry())
        self.setGeometry(rect)

        # 截一张全屏当"冻结背景"，避免遮罩下面还在动
        try:
            scr = QGuiApplication.primaryScreen()
            self._bg = scr.grabWindow(0)
        except Exception:
            self._bg = None

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        if self._bg is not None:
            p.drawPixmap(self.rect(), self._bg)
        p.fillRect(self.rect(), QColor(0, 0, 0, 110))
        if self._start and self._cur:
            r = QRect(self._start, self._cur).normalized()
            p.setCompositionMode(QPainter.CompositionMode_Clear)
            p.fillRect(r, Qt.transparent)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            p.setPen(QPen(QColor(ACCENT), 2))
            p.drawRect(r)

    def mousePressEvent(self, e):
        self._start = e.position().toPoint()
        self._cur = self._start
        self.update()

    def mouseMoveEvent(self, e):
        if self._start:
            self._cur = e.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, e):
        if self._start and self._cur:
            r = QRect(self._start, self._cur).normalized()
            if r.width() > 4 and r.height() > 4:
                self._result = QRect(self.x() + r.x(), self.y() + r.y(),
                                     r.width(), r.height())
        self._done = True
        self.close()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self._done = True
            self.close()


def select_region(parent=None):
    """弹出全屏框选，返回 QRect（屏幕绝对坐标）或 None

    做法：转 Qt 事件循环直到用户松手或按 Esc，再读结果。
    """
    import time
    sel = RegionSelector(parent)
    sel.show()
    sel.raise_()
    sel.activateWindow()
    while not sel._done:
        QGuiApplication.processEvents()
        time.sleep(0.01)
    return sel._result


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

        import sessions
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 16)
        root.setSpacing(8)

        def lab(t, dim=False):
            x = QLabel(t)
            x.setStyleSheet(label_qss(DIM if dim else TEXT, 12))
            return x

        root.addWidget(lab("名称", dim=False))
        self.name_edit = QLineEdit(sessions.display_name(self._rec))
        self.name_edit.setPlaceholderText("留空则用默认名（日期 + 时间 + 时长）")
        root.addWidget(self.name_edit)

        root.addWidget(lab(f"默认名：{sessions.default_name(self._rec)}", dim=True))
        root.addSpacing(4)

        root.addWidget(lab("备注", dim=False))
        self.notes_edit = QPlainTextEdit(sessions.display_notes(self._rec))
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


# ============================================================
#  黑名单 / 白名单 —— 配置单张名单
# ============================================================
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


