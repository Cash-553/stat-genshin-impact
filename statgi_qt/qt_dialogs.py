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
                               QLineEdit, QCheckBox)

import config_manager
import paths
from qt_theme import (TEXT, DIM, ACCENT, CARD, BG, BORDER, panel_alpha, label_qss,
                      btn_qss)
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
    """材料库编辑：查看 / 搜索 / 添加 / 改名 / 删除。

    列表里有三种来源（后面那个小标签）：
        内置 —— materials_db.INITIAL_MATERIALS 里的
        自动 —— 识别到新材料后自动登记进来的
        记录 —— **只出现在收益记录里、没进材料库**的名字

    ⚠ 为什么要有「记录」这一类：
      识别结果记账和「登记进材料库」是两条路 —— 记账走记录文件，
      登记走 materials.json。所以有些名字（尤其是 OCR 认错的）
      会只出现在记录里，光看材料库根本找不到。
      用户反馈过「明明登记了一堆错名字，编辑器里却找不到」，就是这原因。

    改名：双击列表里那一行直接改。
    """

    def __init__(self, parent, alpha=150):
        super().__init__(parent)
        self.setWindowTitle("材料库")
        self.setMinimumSize(640, 680)
        self.alpha = alpha

        import materials_db
        self.db = materials_db
        self._names = []            # 当前列表里显示的名字

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
        root.setSpacing(10)

        self.tip = QLabel("")
        self.tip.setStyleSheet(label_qss(DIM, 13))
        root.addWidget(self.tip)

        # ---- 搜索 + 只看自动 ----
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索材料名…")
        self.search.setFixedHeight(30)
        self.search.textChanged.connect(self._rebuild)
        bar.addWidget(self.search, 1)

        self.only_auto = QCheckBox("只看非内置")
        self.only_auto.setToolTip("隐藏内置的那 84 个，只看自动登记的和记录里的")
        self.only_auto.toggled.connect(self._rebuild)
        bar.addWidget(self.only_auto)

        # 「记录里出现过的名字」默认也列出来 —— 用户就是找不到这些才提的反馈
        self.show_records = QCheckBox("含记录里的名字")
        self.show_records.setChecked(True)
        self.show_records.toggled.connect(self._rebuild)
        bar.addWidget(self.show_records)

        # 官方名字白名单（generated_names.py）里没有的 → 多半是 OCR 读错
        self.only_sus = QCheckBox("只看疑似错名")
        self.only_sus.setToolTip("列出不在官方材料名单里的名字（多半是识别读错的）")
        self.only_sus.toggled.connect(self._rebuild)
        bar.addWidget(self.only_sus)
        root.addLayout(bar)

        # ---- 列表 ----
        self.list = QListWidget()
        self.list.setAlternatingRowColors(False)
        # ⚠ 这里**不能**写 `QListWidget::item { color: ... }` ——
        #   样式表里的 color 会盖掉 QListWidgetItem.setForeground()，
        #   那样按类型上色（疑似红 / 记录灰 / 自动蓝）就全失效了。
        #   默认颜色改用调色板，逐行的颜色在 _rebuild 里 setForeground。
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
        self.new_edit.setPlaceholderText("输入新材料名，回车添加…")
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
                ("加入材料库", "accent", self._on_adopt),
                ("删除选中", "danger", self._on_delete),
                ("恢复默认", "danger", self._on_reset)):
            b = QPushButton(text)
            b.setFixedHeight(32)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(btn_qss(kind, self.alpha))
            b.clicked.connect(cb)
            bottom.addWidget(b)
        bottom.addStretch(1)
        close = QPushButton("关闭")
        close.setFixedSize(84, 32)
        close.setCursor(Qt.PointingHandCursor)
        close.setStyleSheet(btn_qss("normal", self.alpha))
        close.clicked.connect(self.accept)
        bottom.addWidget(close)
        root.addLayout(bottom)

        self._rebuild()

    # ---------- 列表 ----------

    def _all(self):
        try:
            return [m for m in self.db.load_materials() if m.get("name")]
        except Exception:
            return []

    def _record_names(self):
        """收益记录里出现过的材料名 -> 出现总次数"""
        out = {}
        if not self.show_records.isChecked():
            return out
        try:
            import sessions
            for r in sessions.load_sessions():
                for k, v in (r.get("materials", {}) or {}).items():
                    out[str(k)] = out.get(str(k), 0) + int(v or 0)
        except Exception:
            pass
        return out

    @staticmethod
    def _whitelist():
        """官方名字白名单（材料 + 圣遗物）。

        不在这个名单里的名字，多半是 OCR 读错的 ——
        比如「编编花蜜」（错）vs「骗骗花蜜」（对）、「牢固的箭镞」vs「牢固的箭簇」。
        """
        try:
            import generated_names as g
            return set(g.MATERIAL_NAMES) | set(g.ARTIFACT_NAMES)
        except Exception:
            return set()

    def _rebuild(self):
        kw = self.search.text().strip()
        only_auto = self.only_auto.isChecked()
        only_sus = self.only_sus.isChecked()
        WL = self._whitelist()
        lib = self._all()
        lib_names = {str(m["name"]) for m in lib}
        recs = self._record_names()

        # 行 = (名字, 标签, 是不是"只在记录里")
        rows = []
        n_auto = 0
        for m in lib:
            name = str(m["name"])
            auto = not self.db.is_builtin(name)
            if auto:
                n_auto += 1
            tag = "自动" if auto else "内置"
            if WL and name not in WL:
                tag += "　疑似"
            rows.append((name, tag, False))
        n_rec_only = 0
        for name, n in sorted(recs.items(), key=lambda kv: -kv[1]):
            if name not in lib_names:
                tag = f"记录 x{n}"
                if WL and name not in WL:
                    tag += "　疑似"
                rows.append((name, tag, True))
                n_rec_only += 1

        self.list.blockSignals(True)
        self.list.clear()
        self._names = []
        n_sus = 0
        for name, tag, rec_only in rows:
            if only_auto and tag.startswith("内置"):
                continue
            suspect = "疑似" in tag
            if only_sus and not suspect:
                continue
            if kw and kw not in name:
                continue
            if suspect:
                n_sus += 1
            it = QListWidgetItem(f"{name}　　{tag}")
            # 只在记录里的不给改名（改材料库改不动它）
            flags = it.flags() | Qt.ItemIsUserCheckable
            if not rec_only:
                flags |= Qt.ItemIsEditable
            it.setFlags(flags)
            it.setCheckState(Qt.Unchecked)
            it.setData(Qt.UserRole, name)
            it.setData(Qt.UserRole + 1, rec_only)
            if suspect:
                it.setForeground(QColor("#E06C5A"))     # 红：疑似错名
            elif rec_only:
                it.setForeground(QColor(DIM))           # 灰：只在记录里
            elif tag.startswith("自动"):
                it.setForeground(QColor(ACCENT))        # 蓝：自动登记
            else:
                it.setForeground(QColor(TEXT))          # 白：内置
            self.list.addItem(it)
            self._names.append(name)
        self.list.blockSignals(False)

        builtin = len(self.db.INITIAL_MATERIALS)
        self.tip.setText(
            f"材料库 {len(lib)} 个（内置 {builtin}　自动登记 {n_auto}）"
            f"　记录里另有 {n_rec_only} 个不在库里的"
            f"　·　疑似错名 {n_sus} 个（红色，不在官方名单里）")
        self._sync_title()

    def _sync_title(self):
        self.setWindowTitle(f"材料库　共 {len(self._all())} 个")

    def _checked_rows(self):
        """勾选的行 -> [(名字, 是不是只在记录里)]"""
        out = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.checkState() == Qt.Checked:
                out.append((str(it.data(Qt.UserRole)),
                            bool(it.data(Qt.UserRole + 1))))
        return out

    def _on_adopt(self):
        """把「只在记录里」的名字加进材料库（下次识别就能按它归类）"""
        rows = self._checked_rows()
        if not rows:
            QMessageBox.information(self, "提示", "先勾选要加入的名字。")
            return
        mats = self._all()
        have = {str(m["name"]) for m in mats}
        add = [n for n, _ in rows if n not in have]
        if not add:
            QMessageBox.information(self, "提示", "勾选的都已经在材料库里了。")
            return
        for n in add:
            mats.append({"name": n, "icon": n + ".png"})
        self.db.save_materials(mats)
        self._rebuild()
        QMessageBox.information(self, "已加入",
                                f"已把 {len(add)} 个名字加进材料库。")

    def _check_all(self, on):
        self.list.blockSignals(True)
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(Qt.Checked if on else Qt.Unchecked)
        self.list.blockSignals(False)

    # ---------- 增删改 ----------

    def _on_item_changed(self, item):
        """改名：双击编辑完会走这里（勾选框变化也会走，但名字没变就跳过）"""
        if item.data(Qt.UserRole + 1):       # 「记录」那类不给改名
            return
        old = str(item.data(Qt.UserRole))
        new = item.text().strip()
        # 显示文字里带了「　　内置 / 　　自动 / 　　记录 xN」后缀，取前面那一段
        if "　　" in new:
            new = new.split("　　")[0]
        new = new.strip()
        if not new or new == old:
            return
        mats = self._all()
        if any(str(m["name"]) == new for m in mats):
            QMessageBox.warning(self, "重名", f"材料库里已经有「{new}」了。")
            self._rebuild()
            return
        for m in mats:
            if str(m["name"]) == old:
                m["name"] = new
                m["icon"] = new + ".png"
                break
        self.db.save_materials(mats)
        self._rebuild()

    def _on_add(self):
        name = self.new_edit.text().strip()
        if not name:
            return
        mats = self._all()
        if any(str(m["name"]) == name for m in mats):
            QMessageBox.warning(self, "已存在", f"材料库里已经有「{name}」了。")
            return
        mats.append({"name": name, "icon": name + ".png"})
        self.db.save_materials(mats)
        self.new_edit.clear()
        self._rebuild()
        self.list.scrollToBottom()

    def _on_delete(self):
        rows = [n for n, rec_only in self._checked_rows() if not rec_only]
        only_rec = [n for n, rec_only in self._checked_rows() if rec_only]
        if not rows:
            if only_rec:
                QMessageBox.information(
                    self, "提示",
                    f"勾选的 {len(only_rec)} 个都只在记录里，不在材料库里，"
                    f"没有可删的。\n\n（记录里的名字删不掉，它已经记在台账上了）")
            else:
                QMessageBox.information(self, "提示", "先勾选要删除的材料。")
            return
        if QMessageBox.question(
                self, "确认删除",
                f"要从材料库里删除这 {len(rows)} 个吗？\n\n"
                "删掉之后，识别到同名材料会当成新材料（开着自动登记就会再加回来）。"
                + (f"\n\n另外勾选的 {len(only_rec)} 个只在记录里，会跳过。"
                   if only_rec else "")
        ) != QMessageBox.Yes:
            return
        names = set(rows)
        mats = [m for m in self._all() if str(m["name"]) not in names]
        self.db.save_materials(mats)
        self._rebuild()

    def _on_reset(self):
        n = len(self._all())
        if QMessageBox.question(
                self, "恢复默认材料库",
                f"会清掉后加进去的材料名，只留内置的 "
                f"{len(self.db.INITIAL_MATERIALS)} 个。\n\n"
                f"当前一共 {n} 个。确定吗？") != QMessageBox.Yes:
            return
        self.db.reset_to_default()
        self._rebuild()


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
