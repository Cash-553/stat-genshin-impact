# -*- coding: utf-8 -*-
"""监测悬浮窗的「项目设置」窗口 —— **全部用主界面现成的控件搭**。

不再自造控件：侧栏用 NavButton、行用 SettingRow、分组用 Accordion、
标签栏照抄 PageSettings 的做法（TABS + 自画按钮 + QStackedWidget）。

    ┌─ 侧栏 ──┬──────────────────────────────────────────┐
    │ 🎨 预设  │ [☑摩拉] [☐材料] [☑狗粮] [＋]               │
    │ ⚙ 项目   │ ──────────────────────────────────────── │
    │         │ ▸ 基本信息 / ▸ 数值与文字 / ▸ 图标 …        │
    └─────────┴──────────────────────────────────────────┘
"""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
import copy
import json
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QCheckBox, QComboBox, QLineEdit,
                               QSlider, QScrollArea, QFrame, QWidget,
                               QStackedWidget, QColorDialog, QMessageBox,
                               QInputDialog, QMenu, QListWidget, QListWidgetItem,
                               QFileDialog)

import qt_theme as T
from qt_widgets import SettingRow, Accordion, small_button, Switch
from qt_window import NavButton

import bar_items
import icons_lib


def _lab(text, size=13, bold=False, color=None):
    """不画底、不画框的 QLabel（本文件统一用它建标签）。

    ⚠ 对话框那层 QSS 里有一条 `QLabel { ... }`，Qt 的样式引擎会因此把
    QLabel 的 frameWidth 当成 1、顺手画一圈边框 —— 实测就是「标签文字
    外面多一个圆角细框」。必须显式声明 background/border 才能压掉。
    （2026-09-23 用像素聚类定位：label 矩形内恰好 108 个强调色像素）
    """
    w = QLabel(text)
    w.setStyleSheet(T.label_qss(color or T.TEXT, size, bold)
                    + "; background: transparent; border: none;")
    return w


def _fix_label_bg(lab):
    """给 label 的样式补上「不画底」。

    同一个根因：QLabel 从 QSS 级联继承了背景色，Qt 就会把它的底/框画出来。
    NavButton 的 label 由主界面控件自己设样式，我们管不着它，
    只能在拿到之后补一刀。

    ⚠ `NavButton.set_active()` 每次都会重设 label 的样式，所以切换页面后
    必须再补一次 —— 这就是为什么 `_nav()` 里也要调。
    """
    ss = lab.styleSheet()
    if "background" not in ss:
        lab.setStyleSheet(ss + "; background: transparent; border: none;")


class BarEditorDialog(QDialog):
    """监测悬浮窗的项目设置窗口。"""

    def __init__(self, parent=None, alpha=150, on_apply=None):
        super().__init__(parent)
        self.setWindowTitle("监测悬浮窗 · 项目设置")
        self.setMinimumSize(1060, 720)
        self.alpha = alpha
        self._on_apply = on_apply
        self._cfg = bar_items.load()
        self._sel = 0
        self._loading = False
        # 当前这套配置是从哪套预设来的（空 = 认不出来）。
        # 经典/直播间是内置模板，它们的定义**永远不动**；
        # 改了设置就是改了「当前配置」，所以要明确告诉用户已经偏离模板。
        self._preset = self._detect_preset()

        self.setStyleSheet(f"""
            QDialog {{ background: {T.BG}; }}
            QLabel {{ color: {T.TEXT}; background: transparent; }}
            QScrollArea, QScrollArea > QWidget > QWidget {{
                background: transparent; border: none;
            }}
            QLineEdit, QComboBox {{
                background: rgba(255,255,255,22); color: {T.TEXT};
                border: 1px solid {T.BORDER}; border-radius: 6px;
                padding: 2px 6px; min-height: 22px;
            }}
            QLineEdit:disabled, QComboBox:disabled {{ color: {T.DIM}; }}
            QCheckBox {{ color: {T.TEXT}; spacing: 7px; }}
            QCheckBox::indicator {{ width: 14px; height: 14px; border-radius: 3px;
                border: 1px solid rgba(255,255,255,80); background: transparent; }}
            QCheckBox::indicator:checked {{ background: {T.ACCENT};
                border: 1px solid {T.ACCENT}; }}
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)
        self.page_title = _lab("监测悬浮窗", 22, True, T.ACCENT)
        root.addWidget(self.page_title)
        # 「当前是/已偏离哪套预设」不再放这里 —— 用户要求在**项目页上方**
        # 显示「正在编辑哪一项预设」，见 _page_items 的 edit_hint。
        # 两处都放就成了同一个信息显示两遍。

        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(self._build_nav())
        self.stack = QStackedWidget()
        self.stack.addWidget(self._page_presets())
        self.stack.addWidget(self._page_items())
        body.addWidget(self.stack, 1)
        root.addLayout(body, 1)

        # 底部不再放「完成」—— 保存 / 取消在**项目页右下角**（见 _page_items）。
        # 预设页不需要底部按钮：点一下卡片就进去了。
        self._nav(0)
        self._refresh_preset_hint()

    # ============================================================
    #  左侧栏（NavButton，跟主界面侧栏一个观感）
    # ============================================================
    def _build_nav(self):
        box = QFrame()
        box.setFixedWidth(150)
        box.setStyleSheet(f"QFrame {{ background: {T.SIDEBAR}; border: none;"
                          " border-radius: 10px; }")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(8, 10, 8, 10)
        lay.setSpacing(3)
        self.nav_btns = []
        for i, (icon, name) in enumerate((("palette", "预设"),
                                          ("settings", "项目"))):
            b = NavButton(box, icon, name)
            b.clicked.connect(lambda _c=False, idx=i: self._nav(idx))
            _fix_label_bg(b.label)
            lay.addWidget(b)
            self.nav_btns.append(b)
        lay.addStretch(1)
        return box

    def _nav(self, idx):
        self.stack.setCurrentIndex(idx)
        for i, b in enumerate(self.nav_btns):
            b.set_active(i == idx)
            _fix_label_bg(b.label)
        self.page_title.setText("监测悬浮窗 · " + ("预设" if idx == 0 else "项目"))
        self._refresh_edit_hint()

    # ============================================================
    #  预设页（折叠卡片）
    # ============================================================
    def _page_presets(self):
        sc, lay = self._scroll()
        # 顶部提示（用户要求）
        hint = _lab("建议先创建预设，再进行修改"
                    "（内置预设是只读的，改不了）", 12, color="#E0A75A")
        hint.setWordWrap(True)
        hint.setStyleSheet(
            T.label_qss("#E0A75A", 12)
            + "; background: rgba(224,167,90,32); border-radius: 6px;"
              " padding: 6px 10px;")
        lay.addWidget(hint)
        for name in bar_items.preset_names():
            lay.addWidget(self._preset_card(name,
                                            bar_items.is_builtin_preset(name)))
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(small_button("把现在的样子存为预设…", self._save_preset,
                                 self.alpha, kind="accent", width=190))
        h.addStretch(1)
        a = Accordion(self, "plus", "新建预设", "把当前这套配置存成一个新预设",
                      items=[("plus", "存为…", "给这套预设起个名字", box)],
                      alpha=self.alpha)
        a.setFixedWidth(660)
        lay.addWidget(a)
        lay.addStretch(1)
        return self._wrap(sc)

    def _preset_card(self, name, builtin):
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        # 「使用」和「查看」分开（用户要求）：
        #   使用 = 就用这套配置，不进去看 -> 直接回主界面
        #   查看 = 进去看看它长什么样 -> 进项目页（内置的是只读）
        h.addWidget(small_button("使用", lambda: self._use_preset(name),
                                 self.alpha, kind="accent", width=68))
        h.addWidget(small_button("查看", lambda: self._view_preset(name),
                                 self.alpha, width=68))
        h.addWidget(small_button("复制", lambda: self._copy_preset(name),
                                 self.alpha, width=68))
        h.addWidget(small_button("改名", lambda: self._rename_preset(name),
                                 self.alpha, width=68))
        h.addWidget(small_button("删除", lambda: self._del_preset(name),
                                 self.alpha, kind="danger", width=68))
        h.addStretch(1)
        desc = ("内置预设无法修改，请复制后再修改"
                if builtin else "你自己存的预设，可以直接改")
        a = Accordion(self, "file-text" if builtin else "palette", name, desc,
                      items=[("palette", "操作",
                              "使用 / 查看 / 复制 / 改名 / 删除", box)],
                      alpha=self.alpha)
        a.setFixedWidth(660)
        return a

    def _refresh_presets(self):
        old = self.stack.widget(0)
        self.stack.removeWidget(old)
        old.setParent(None)
        old.deleteLater()
        self.stack.insertWidget(0, self._page_presets())
        self._nav(0)

    def _use_preset(self, name):
        """使用这套配置 —— **不关闭编辑窗口**，直接切到项目页让你接着改。

        （用户明确要求：选「使用」后不要退出编辑窗口。以前这里会
        accept() 把整个窗口关掉，现在改成应用完就留在编辑器里。）

        复制品和内置都一样：点了就是「现在用这套」。
        之后想改随时改（内置的进「查看」才是只读）。
        """
        if QMessageBox.question(
                self, "使用预设",
                f"用「{name}」这套配置？当前配置会被盖掉。"
                ) != QMessageBox.Yes:
            return
        self._cfg = bar_items.apply_preset(name)
        # 使用 ≠ 正在查看：清掉查看态，这样保存不会被只读 Guard 挡住
        self._preset = ""
        self._rebuild_tabs()
        self._load_item()
        self._save()
        self._set_status(f"已使用「{name}」")
        self._nav(1)                 # 进项目页继续编辑，**不关窗口**

    def _view_preset(self, name):
        """进去看这套预设的配置。

        内置预设（经典 / 直播间）进去是**只读**的：所有控件置灰，
        上面提示「内置预设无法修改，请复制后再修改」。
        """
        if QMessageBox.question(
                self, "查看预设",
                f"进去看「{name}」的配置？当前配置会被这套盖掉。"
                ) != QMessageBox.Yes:
            return
        self._cfg = bar_items.apply_preset(name)
        self._preset = name          # 记住来路：只读判断和上方提示都靠它
        self._rebuild_tabs()
        self._load_item()
        self._save()
        self._nav(1)                 # 进项目页

    def _copy_preset(self, name):
        """复制一套预设，复制出来的那份可以随便改。

        名字冲突就自动加 _2 / _3 …
        """
        src = bar_items.all_presets().get(name)
        if not src:
            QMessageBox.warning(self, "复制失败", f"找不到预设「{name}」。")
            return
        base = f"{name} 副本"
        new = base
        i = 2
        while new in bar_items.preset_names():
            new = f"{base}{i}"
            i += 1
        if not bar_items.save_preset(new, copy.deepcopy(src)):
            QMessageBox.warning(self, "复制失败", "存不下，名字可能冲突了。")
            return
        self._refresh_presets()
        # 复制完直接进去编辑 —— 省一步
        self._cfg = bar_items.apply_preset(new)
        self._preset = new
        self._rebuild_tabs()
        self._load_item()
        self._save()
        self._nav(1)
        self._set_status(f"已复制为「{new}」")

    def _apply_preset(self, name):
        """（旧入口，保留给验证脚本用）等同于「查看」"""
        self._view_preset(name)

    def _save_preset(self):
        name, ok = QInputDialog.getText(self, "存为预设", "预设叫什么名字？",
                                        text="我的样式")
        name = name.strip() if ok else ""
        if not name:
            return
        if name in bar_items.preset_names():
            QMessageBox.warning(self, "重名", f"已经有叫「{name}」的预设了。")
            return
        bar_items.save(self._cfg)
        bar_items.save_preset(name, bar_items.load())
        self._refresh_presets()

    def _rename_preset(self, name):
        new, ok = QInputDialog.getText(self, "重命名预设", "新名字：", text=name)
        new = new.strip() if ok else ""
        if not new:
            return
        if not bar_items.rename_preset(name, new):
            QMessageBox.warning(self, "失败", "改名没成功（重名了？）。")
            return
        self._refresh_presets()

    def _del_preset(self, name):
        if QMessageBox.question(self, "删除预设",
                                f"要删掉「{name}」吗？") != QMessageBox.Yes:
            return
        bar_items.delete_preset(name)
        self._refresh_presets()

    # ============================================================
    #  项目页（标签栏 + 设置）
    # ============================================================
    def _page_items(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        # 「当前正在编辑哪一项预设」—— 项目页上方那一行
        self.edit_hint = _lab("", 14, True, T.ACCENT)
        outer.addWidget(self.edit_hint)

        # 内置预设的只读提示（用户要求的那句）
        self.ro_banner = _lab("", 12)
        self.ro_banner.hide()
        outer.addWidget(self.ro_banner)

        self.tab_bar = QWidget()
        self.tab_row = QHBoxLayout(self.tab_bar)
        self.tab_row.setContentsMargins(0, 0, 0, 0)
        self.tab_row.setSpacing(6)
        outer.addWidget(self.tab_bar)

        sc, lay = self._scroll()
        self._build_fields(lay)
        self.scroll = sc
        outer.addWidget(sc, 1)

        # 右下角：保存 / 取消 —— 按完都回预设界面
        foot = QHBoxLayout()
        foot.addStretch(1)
        self.btn_cancel = small_button("取消", self._cancel_edit, self.alpha,
                                       width=88, height=32)
        self.btn_save = small_button("保存", self._save_and_back, self.alpha,
                                     kind="accent", width=88, height=32)
        foot.addWidget(self.btn_cancel)
        foot.addWidget(self.btn_save)
        outer.addLayout(foot)

        self._rebuild_tabs()
        self._load_item()
        self._apply_readonly()
        return page

    def _is_readonly(self):
        """现在看的是不是内置预设（经典 / 直播间）。

        用户要的行为：用这两套时页面上所有配置都能**看到**，
        但全是灰的改不了，上面提示「内置预设无法修改，请复制后再修改」。
        """
        return bool(self._preset) and bar_items.is_builtin_preset(self._preset)

    def _apply_readonly(self):
        """按内置 / 自建预设切换只读状态"""
        ro = self._is_readonly()
        if ro:
            self.ro_banner.setText(
                f"内置预设无法修改，请复制后再修改"
                f"（回预设页点「{self._preset}」那行的「复制」）")
            self.ro_banner.setStyleSheet(
                T.label_qss("#E0A75A", 12)
                + "; background: rgba(224,167,90,32); border-radius: 6px;"
                  " padding: 6px 10px;")
            self.ro_banner.show()
        else:
            self.ro_banner.hide()

        # ⚠ 不要对整个 scroll 调 setEnabled(False)：那样折叠分组也点不开了，
        #   用户就**看不到**里面的配置。要的是「能看、不能改」——
        #   所以只把可交互控件逐个禁掉，分组标题保持可点。
        if hasattr(self, "scroll"):
            self._set_controls_enabled(self.scroll, not ro)
        # 保存 / 取消：取消还能用来退出，保存没意义
        if hasattr(self, "btn_save"):
            self.btn_save.setEnabled(not ro)
            self.btn_cancel.setText("返回" if ro else "取消")
        # 标签上的开关和「＋」也不许动
        for box, sw in getattr(self, "tab_btns", []):
            sw.setEnabled(not ro)
            box.setCursor(Qt.ArrowCursor if ro else Qt.PointingHandCursor)
        if hasattr(self, "add_btn"):
            self.add_btn.setEnabled(not ro)
        return ro

    @staticmethod
    def _set_controls_enabled(root, on):
        """把 root 下的输入类控件全部启用 / 禁用。

        只碰真正能改数据的控件（滑块 / 下拉 / 输入框 / 勾选框 / 通用按钮），
        折叠分组本身不动 —— 这样只读时依然能展开来看。
        """
        from PySide6.QtWidgets import (QAbstractSlider, QComboBox, QLineEdit,
                                       QAbstractButton)
        kinds = (QAbstractSlider, QComboBox, QLineEdit, QAbstractButton)
        # 这些按钮是「选颜色」那种，纯外观辅助，不碰数据，一起灰掉更清楚
        keep_enabled = ()
        for w in root.findChildren(QWidget):
            if not isinstance(w, kinds):
                continue
            if isinstance(w, keep_enabled):
                continue
            w.setEnabled(on)

    def _save_and_back(self):
        """保存当前改动 —— **留在编辑窗口**，不退出。

        （用户要求：选「使用」后不要退出编辑窗口。以前保存会跳回预设页，
        改成原地保存 + 状态提示就行。）
        """
        self._save()
        self._set_status("已保存")

    def _cancel_edit(self):
        """放弃自上次保存以来的改动。

        「取消」要真的撤销：重新从磁盘读回来（`_save()` 是即时落盘的，
        所以磁盘上的就是最后一次保存的状态）。撤销完回预设界面。
        """
        self._cfg = bar_items.load()
        self._sel = 0
        self._rebuild_tabs()
        self._load_item()
        self._back_to_presets("已取消")

    def _back_to_presets(self, tail=""):
        self._refresh_presets()          # 里面会 _nav(0) + 重建预设页

    def _refresh_edit_hint(self):
        """项目页上方那行：现在在编辑哪一项预设"""
        if not hasattr(self, "edit_hint"):
            return
        if self._preset and not self._preset_drifted():
            self.edit_hint.setText(f"正在编辑「{self._preset}」预设")
        elif self._preset:
            self.edit_hint.setText(
                f"正在编辑「{self._preset}」的改动"
                f"（{self._preset} 这套预设本身没动）")
        else:
            near = self._closest_preset()
            if near:
                self.edit_hint.setText(
                    f"正在编辑自定义配置（从「{near}」改来的）")
            else:
                self.edit_hint.setText("正在编辑自定义配置")

    def _rebuild_tabs(self):
        while self.tab_row.count():
            it = self.tab_row.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
        self.tab_btns = []
        for idx, it in enumerate(self._cfg.get("items") or []):
            box = QFrame()
            box.setCursor(Qt.PointingHandCursor)
            h = QHBoxLayout(box)
            h.setContentsMargins(10, 6, 12, 6)
            h.setSpacing(6)
            sw = Switch(box, bool(it.get("visible", True)))
            sw.setToolTip("要不要显示这一项")
            sw.toggled.connect(lambda v, i=idx: self._set_visible(i, v))
            h.addWidget(sw)
            h.addWidget(_lab(str(it.get("title") or it.get("id") or f"项目{idx+1}")))
            box.setContextMenuPolicy(Qt.CustomContextMenu)
            box.customContextMenuRequested.connect(
                lambda p, i=idx: self._tab_menu(i, p))
            box.mousePressEvent = lambda _e, i=idx: self._pick_tab(i)
            self.tab_row.addWidget(box)
            self.tab_btns.append((box, sw))
        add = QPushButton("＋")
        add.setFixedSize(36, 30)
        add.setCursor(Qt.PointingHandCursor)
        add.setToolTip("添加项目")
        add.setStyleSheet(T.btn_qss("normal", self.alpha))
        add.clicked.connect(self._on_add)
        self.add_btn = add
        self.tab_row.addWidget(add)
        self.tab_row.addStretch(1)
        self._sync_tabs()
        self._apply_readonly()

    def _sync_tabs(self):
        for i, (box, _cb) in enumerate(getattr(self, "tab_btns", [])):
            on = (i == self._sel)
            box.setStyleSheet(
                f"QFrame {{ background: {T.CARD}; border-radius: 8px;"
                + (f" border: 1px solid {T.ACCENT};" if on else " border: none;")
                + " }")

    def _pick_tab(self, idx):
        self._sel = max(0, min(len(self._cfg["items"]) - 1, idx))
        self._load_item()
        self._sync_tabs()

    def _tab_menu(self, idx, pos):
        """标签上右键：删除这个项目"""
        m = QMenu(self)
        m.setStyleSheet(f"""
            QMenu {{ background: {T.CARD}; color: {T.TEXT};
                     border: 1px solid {T.BORDER}; border-radius: 8px; padding: 5px; }}
            QMenu::item {{ padding: 6px 20px; border-radius: 5px; }}
            QMenu::item:selected {{ background: {T.ACCENT}; color: #10161f; }}
        """)
        m.addAction("显示这一项" if not self._cfg["items"][idx].get("visible", True)
                    else "隐藏这一项").triggered.connect(
            lambda _c=False, i=idx: self._set_visible(
                i, not self._cfg["items"][i].get("visible", True)))
        m.addSeparator()
        m.addAction("删除这个项目").triggered.connect(
            lambda _c=False, i=idx: self._del_item(i))
        m.exec(self.tab_bar.mapToGlobal(pos) if pos else self.cursor().pos())

    def _del_item(self, idx):
        if len(self._cfg.get("items") or []) <= 1:
            QMessageBox.information(self, "提示", "至少要留一个项目。")
            return
        it = self._cfg["items"][idx]
        if QMessageBox.question(
                self, "删除项目",
                f"要删掉「{it.get('title') or it.get('id')}」吗？"
                ) != QMessageBox.Yes:
            return
        self._cfg["items"].pop(idx)
        self._sel = max(0, idx - 1)
        self._rebuild_tabs()
        self._load_item()
        self._save()

    def _set_visible(self, idx, on):
        if self._loading:
            return
        self._cfg["items"][idx]["visible"] = bool(on)
        self._save()

    def _on_add(self):
        labels = [n for _v, n, _d in bar_items.SOURCES]
        kind, ok = QInputDialog.getItem(self, "添加项目", "要显示什么？",
                                        labels, 0, False)
        if not ok:
            return
        val = {n: v for v, n, _d in bar_items.SOURCES}[kind]
        new = bar_items.new_item("text" if val == "text" else
                                 ("time" if val == "runtime" else "number"))
        new["source"] = val
        new["type"] = ("text" if val == "text" else
                       ("time" if val == "runtime" else "number"))
        new["title"] = kind
        if val == "material":
            m = self._ask_material()
            if not m:
                return
            new["material"] = m
            new["title"] = m
        items = self._cfg.get("items") or []
        if items:
            cur = items[self._sel]
            for k in ("width", "height", "radius", "padding", "bg_color",
                      "bg_alpha", "border", "border_color", "border_alpha",
                      "border_width", "shadow", "value_size", "value_color",
                      "label_size", "label_color", "title_size", "title_color",
                      "num_bold", "show_title"):
                if k in cur:
                    new[k] = cur[k]
        self._cfg["items"].append(new)
        self._sel = len(self._cfg["items"]) - 1
        self._rebuild_tabs()
        self._load_item()
        self._save()

    def _ask_material(self):
        try:
            import names_db
            mats = sorted(names_db.material_set())
        except Exception:
            mats = []
        if not mats:
            QMessageBox.information(self, "没有材料名单",
                                    "识别名单是空的，先在「设置 → 统计 → 识别名单」里加。")
            return ""
        dlg = MaterialPicker(self, mats, self.alpha)
        if dlg.exec() != QDialog.Accepted:
            return ""
        return dlg.chosen()

    # ============================================================
    #  设置控件
    # ============================================================
    def _scroll(self):
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        sc.setStyleSheet("QScrollArea { background: transparent; border: none; }"
                         "QScrollArea > QWidget > QWidget { background: transparent; }")
        holder = QWidget()
        lay = QVBoxLayout(holder)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(6)
        sc.setWidget(holder)
        return sc, lay

    def _wrap(self, sc):
        w = QWidget()
        h = QVBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(sc)
        return w

    def _edit(self, key, width=200):
        w = QLineEdit()
        w.setFixedWidth(width)
        w.textChanged.connect(lambda _t, k=key: self._on_change(k))
        return w

    def _chk(self, key, text="开启"):
        w = QCheckBox(text)
        w.toggled.connect(lambda _v, k=key: self._on_change(k))
        return w

    def _slider(self, key, lo, hi, unit=""):
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        s = QSlider(Qt.Horizontal)
        s.setRange(lo, hi)
        s.setFixedWidth(160)
        s.setStyleSheet(T.slider_qss())
        v = _lab("", 12, color=T.ACCENT)
        v.setFixedWidth(48)
        s.valueChanged.connect(
            lambda val, k=key, l=v, u=unit: (l.setText(f"{val}{u}"),
                                             self._on_change(k)))
        s._val, s._unit = v, unit
        h.addWidget(s)
        h.addWidget(v)
        return box, s

    def _color_btn(self, key, optional=False):
        w = QPushButton("跟随主题" if optional else "选颜色")
        w.setMinimumWidth(124)
        w.setFixedHeight(26)
        w.setCursor(Qt.PointingHandCursor)
        w.setStyleSheet(T.btn_qss("normal", self.alpha))
        w.clicked.connect(lambda _c=False, k=key, o=optional:
                          self._pick_color(k, o))
        return w

    def _combo(self, key, choices, width=150):
        w = QComboBox()
        for n, v in choices:
            w.addItem(n, v)
        w.setFixedWidth(width)
        w.setStyleSheet(T.combo_qss())
        w.currentIndexChanged.connect(lambda _i, k=key: self._on_change(k))
        return w

    def _build_fields(self, lay):
        I = {}
        I["title"] = self._edit("title")
        I["source"] = QComboBox()
        I["source"].addItems([n for _v, n, _d in bar_items.SOURCES])
        I["source"].setFixedWidth(180)
        I["source"].setStyleSheet(T.combo_qss())
        I["source"].currentIndexChanged.connect(lambda _i: self._on_source())
        I["src_desc"] = _lab("", 12, color=T.DIM)

        # 「数值与文字」只留两个勾选框（用户 2026-09-23 定的）。
        # 前缀 / 后缀 / 显示这一项 / 千分位 / 大数用万 / 数值为 0 时隐藏 /
        # 每小时速率 / 标题放数值下面 —— 这 8 项的界面已删。
        # ⚠ 配置里这些字段**仍然保留并按原样生效**（比如直播间预设的
        #   prefix="×"），只是不再给界面入口，别把它们从 bar_items 里删掉。
        #   项目的显示/隐藏改由标签栏上的 Switch 控制。
        for k, txt in (("show_title", "显示标题"), ("show_value", "显示数值")):
            I[k] = self._chk(k, txt)
        I["icon_on"] = self._chk("show_icon", "显示图标")

        I["icon"] = QComboBox()
        I["icon"].setFixedWidth(180)
        I["icon"].setStyleSheet(T.combo_qss())
        I["icon"].currentTextChanged.connect(lambda _t: self._on_change("icon"))
        ibox = QWidget()
        ih = QHBoxLayout(ibox)
        ih.setContentsMargins(0, 0, 0, 0)
        ih.addWidget(I["icon"])
        ih.addWidget(small_button("导入…", self._import_icon, self.alpha,
                                  width=68))
        ih.addWidget(small_button("删掉", self._remove_icon, self.alpha,
                                  kind="danger", width=58))
        ih.addWidget(small_button("选图标…", self._pick_icon, self.alpha,
                                  width=88))
        I["icon_w"] = ibox
        I["icon_size"], _ = self._slider("icon_size", 12, 90, " px")
        I["icon_pos"] = self._combo("icon_pos", [("上方", "top"),
                                                ("下方", "bottom"),
                                                ("左侧", "left"),
                                                ("右侧", "right")], 130)

        I["width"], _ = self._slider("width", 40, 600, " px")
        I["height"], _ = self._slider("height", 24, 300, " px")
        I["radius"], _ = self._slider("radius", 0, 150, " px")
        I["padding"], _ = self._slider("padding", 0, 60, " px")
        I["bg_alpha"], _ = self._slider("bg_alpha", 0, 255)
        I["border_width"], _ = self._slider("border_width", 1, 10, " px")
        I["border_alpha"], _ = self._slider("border_alpha", 0, 255)
        I["bg_color"] = self._color_btn("bg_color")
        I["border"] = self._chk("border", "显示边框")
        I["border_color"] = self._color_btn("border_color")
        I["shadow"] = self._chk("shadow", "显示阴影")
        I["value_size"], _ = self._slider("value_size", 8, 60, " px")
        I["value_color"] = self._color_btn("value_color", True)
        I["num_bold"] = self._chk("num_bold", "加粗")
        I["title_size"], _ = self._slider("title_size", 8, 40, " px")
        I["title_color"] = self._color_btn("title_color", True)
        self.f = I

        # ---- 分组（每行都是主界面的 SettingRow）----
        def group(rows):
            w = QWidget()
            v = QVBoxLayout(w)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(0)
            for icon, name, desc, ctrl in rows:
                v.addWidget(SettingRow(self, icon, name, desc, ctrl,
                                       alpha=self.alpha, height=62))
            return w

        lay.addWidget(self._acc("file-text", "基本信息", "项目名称与数据来源",
                                group([
            ("file-text", "项目名称", "标题行显示的文字", I["title"]),
            ("settings", "显示什么数据", "选择要显示的数据项", I["source"]),
            ("settings", "当前数据源", "当前所选材料",
             I["src_desc"])])))

        lay.addWidget(self._acc("sliders-horizontal", "数值与文字",
                                "数值格式与标题排布", group([
            ("eye", "显示标题", "是否显示标题行", I["show_title"]),
            ("hash", "显示数值", "是否显示数值", I["show_value"])])))

        # 图标这一组：只有摩拉 / 材料 / 狗粮才显示
        self.icon_group = self._acc("image", "图标",
                                    "仅摩拉 / 材料 / 狗粮支持图标", group([
            ("eye", "显示图标", "是否显示图标", I["icon_on"]),
            ("image", "图标文件", "图标文件", I["icon_w"]),
            ("image", "图标大小", "图标尺寸", I["icon_size"]),
            ("image", "图标位置", "图标相对位置", I["icon_pos"])]))
        lay.addWidget(self.icon_group)

        lay.addWidget(self._acc("square", "卡片外观", "卡片尺寸、配色与边框", group([
            ("square", "宽度", "卡片宽度", I["width"]),
            ("square", "高度", "卡片高度", I["height"]),
            ("square", "圆角", "0 为直角", I["radius"]),
            ("square", "内边距", "内容与卡片边缘的距离", I["padding"]),
            ("palette", "背景颜色", "卡片背景色", I["bg_color"]),
            ("sun", "背景透明度", "0 为完全透明", I["bg_alpha"]),
            ("square", "显示边框", "是否显示边框", I["border"]),
            ("palette", "边框颜色", "边框颜色", I["border_color"]),
            ("sun", "边框透明度", "0 为不显示边框", I["border_alpha"]),
            ("square", "边框宽度", "边框线宽", I["border_width"]),
            ("sun", "显示阴影", "是否绘制投影", I["shadow"])])))

        lay.addWidget(self._acc("file-text", "字体与颜色", "数值与标题的字号颜色",
                                group([
            ("file-text", "数值字号", "数值字号", I["value_size"]),
            ("palette", "数值颜色", "留空则跟随界面主题", I["value_color"]),
            ("file-text", "数值加粗", "数值加粗", I["num_bold"]),
            ("file-text", "标题字号", "标题字号", I["title_size"]),
            ("palette", "标题颜色", "留空则跟随界面主题", I["title_color"])])))

        # 把这一项的卡片外观复制给所有项目
        allbox = QWidget()
        ah = QHBoxLayout(allbox)
        ah.setContentsMargins(0, 0, 0, 0)
        ah.addWidget(small_button("把这一项的卡片外观应用到全部项目",
                                  self._apply_to_all, self.alpha,
                                  kind="accent", width=250))
        ah.addStretch(1)
        lay.addWidget(self._acc("layout-dashboard", "批量",
                                "把当前项的外观复制到其余项目",
                                allbox))
        lay.addStretch(1)

    def _apply_to_all(self):
        it = self._item()
        if it is None:
            return
        if QMessageBox.question(
                self, "应用到全部",
                "把当前这一项的卡片外观（尺寸 / 底色 / 圆角 / 边框 / 字体）"
                "套给所有项目？") != QMessageBox.Yes:
            return
        keys = ("width", "height", "radius", "padding", "bg_color", "bg_alpha",
                "border", "border_color", "border_alpha", "border_width",
                "shadow", "value_size", "value_color", "num_bold",
                "label_size", "label_color", "title_size", "title_color")
        for other in self._cfg["items"]:
            for k in keys:
                if k in it:
                    other[k] = it[k]
        self._rebuild_tabs()
        self._load_item()
        self._save()

    def _acc(self, icon, title, desc, body):
        a = Accordion(self, icon, title, desc, items=[], body_widget=body,
                      alpha=self.alpha)
        a.setFixedWidth(700)
        return a

    # ============================================================
    #  载入 / 保存
    # ============================================================
    def _item(self):
        items = self._cfg.get("items") or []
        if not items:
            return None
        self._sel = max(0, min(len(items) - 1, self._sel))
        return items[self._sel]

    def _load_item(self):
        it = self._item()
        if it is None:
            return
        self._loading = True
        f = self.f
        f["title"].setText(str(it.get("title") or ""))
        vals = [v for v, _n, _d in bar_items.SOURCES]
        src = str(it.get("source") or "mora")
        f["source"].setCurrentIndex(vals.index(src) if src in vals else 0)
        f["src_desc"].setText(
            f"材料：{it.get('material')}" if src == "material"
            else bar_items.SOURCE_DESC.get(src, ""))
        for k, key in (("show_title", "show_title"), ("show_value", "show_value"),
                       ("icon_on", "show_icon"), ("border", "border"),
                       ("shadow", "shadow"), ("num_bold", "num_bold")):
            w = f[k]
            w.blockSignals(True)
            w.setChecked(bool(it.get(key, k in ("show_title", "show_value"))))
            w.blockSignals(False)
        # 下拉框里「列的是库里有的」，而它要显示的值来自项目本身 ——
        # 所以先按项目重建列表，再把选中项切过去（顺序反了会显示错）
        self._reload_icons()
        self._set_icon_file(str(it.get("icon") or ""))
        for k in ("icon_size", "width", "height", "radius", "padding",
                  "bg_alpha", "border_width", "border_alpha", "value_size",
                  "title_size"):
            s = f[k].findChild(QSlider)
            if s is not None:
                s.blockSignals(True)
                s.setValue(int(it.get(k, 0) or 0))
                s.blockSignals(False)
                s._val.setText(f"{s.value()}{s._unit}")
        for k, opt in (("bg_color", False), ("border_color", False),
                       ("value_color", True), ("title_color", True)):
            self._paint(f[k], str(it.get(k) or ""), opt)
        f["icon_pos"].blockSignals(True)
        f["icon_pos"].setCurrentIndex(
            {"top": 0, "bottom": 1, "left": 2, "right": 3}
            .get(str(it.get("icon_pos")), 0))
        f["icon_pos"].blockSignals(False)
        self._loading = False
        self._sync_icon_group()
        self._set_status()
        # ⚠ 必须放最后：_load_item 会重建图标下拉等控件，新控件的 enabled
        # 是默认值（可点），不重新套一遍只读状态，内置预设就又变成可改了
        self._apply_readonly()

    def _sync_icon_group(self):
        it = self._item()
        src = str(it.get("source") if it else "mora")
        if hasattr(self, "icon_group"):
            self.icon_group.setVisible(
                src in ("mora", "material_total", "artifact"))

    def _on_source(self):
        if self._loading or self._is_readonly():
            return
        it = self._item()
        if it is None:
            return
        val = [v for v, _n, _d in bar_items.SOURCES][
            self.f["source"].currentIndex()]
        it["source"] = val
        it["type"] = ("text" if val == "text" else
                      ("time" if val == "runtime" else "number"))
        if val == "material":
            m = self._ask_material()
            if m:
                it["material"] = m
                it["title"] = m
        self._save()
        self._load_item()
        self._rebuild_tabs()

    def _on_change(self, key):
        if self._loading or self._is_readonly():
            return
        it = self._item()
        if it is None:
            return
        f = self.f
        if key == "title":
            # 前缀 / 后缀的界面入口已删，但配置字段照旧生效（见 _build_fields）
            it[key] = f[key].text()
        elif key == "icon":
            it["icon"] = self._icon_file()
        elif key == "show_icon":
            it["show_icon"] = bool(f["icon_on"].isChecked())
        elif key == "icon_pos":
            it["icon_pos"] = f["icon_pos"].currentData() or "top"
        elif key in ("show_title", "show_value",
                     "border", "shadow", "num_bold"):
            it[key] = bool(f[key].isChecked())
        elif key in ("icon_size", "width", "height", "radius", "padding",
                     "bg_alpha", "border_width", "border_alpha", "value_size",
                     "title_size"):
            s = f[key].findChild(QSlider)
            if s is not None:
                it[key] = int(s.value())
        else:
            return
        if key == "title":
            self._rebuild_tabs()
        self._save()

    def _pick_icon(self):
        """从图标库里挑一个（列表只列默认三个 + 自己导入的）"""
        files = icons_lib.available_files()
        labels = [icons_lib.display(f) for f in files]
        cur = self._icon_file()
        idx = files.index(cur) if cur in files else 0
        t, ok = QInputDialog.getItem(self, "选择图标", "用哪个图标？",
                                     labels, idx, False)
        if ok and t in labels:
            self._set_icon_file(files[labels.index(t)])

    # ---- 图标库 ----

    def _reload_icons(self):
        """重建图标下拉框。用 userData 存真实文件名，显示名另算 ——
        这样三个默认图标能显示成「摩拉（mora.png）」这种好认的样子。
        """
        cb = self.f.get("icon") if hasattr(self, "f") else None
        if cb is None:
            return
        cur = self._icon_file()
        cb.blockSignals(True)
        cb.clear()
        cb.addItem("（无）", "")
        files = icons_lib.available_files()
        for fn in files:
            cb.addItem(icons_lib.display(fn), fn)
        want = cur if icons_lib.is_available(cur) else ""
        i = cb.findData(want)
        cb.setCurrentIndex(i if i >= 0 else 0)
        cb.blockSignals(False)

    def _icon_file(self):
        """当前下拉框选中的真实文件名"""
        cb = self.f.get("icon") if hasattr(self, "f") else None
        if cb is None:
            return ""
        d = cb.currentData()
        return str(d) if d is not None else ""

    def _set_icon_file(self, fname):
        cb = self.f["icon"]
        i = cb.findData(str(fname))
        if i < 0:                      # 不在库里（老配置引用了已移除的图标）
            cb.addItem(icons_lib.display(fname), fname)
            i = cb.count() - 1
        cb.setCurrentIndex(i)
        self._on_change("icon")

    def _import_icon(self):
        """从任意位置导入图片到图标库"""
        fs, _ = QFileDialog.getOpenFileNames(
            self, "导入图标", "",
            "图片 (*.png *.jpg *.jpeg *.webp *.bmp *.gif);;所有文件 (*)")
        if not fs:
            return
        ok, skipped = icons_lib.import_files(fs)
        self._reload_icons()
        if ok:
            self._set_icon_file(ok[0])
        if skipped:
            QMessageBox.warning(self, "有文件没导入", "\n".join(skipped))
        if ok:
            self._set_status(f"已导入 {len(ok)} 个图标")

    def _remove_icon(self):
        """删掉一个自己导入的图标（会先备份到 icons\\_已移除\\）"""
        fname = self._icon_file()
        if not fname or not icons_lib.is_available(fname):
            QMessageBox.information(self, "没选图标", "先在下拉框里选一个图标。")
            return
        if fname in icons_lib.default_files():
            QMessageBox.information(
                self, "这是默认图标",
                "摩拉 / 材料 / 狗粮 是内置的，不能删。\n"
                "想换的话，导入一张自己的图，然后在下拉框里选它。")
            return
        if QMessageBox.question(
                self, "删掉图标",
                f"要把「{icons_lib.display(fname)}」从图标库删掉吗？\n"
                "（会先备份到 icons\\_已移除\\，还能捞回来）"
                ) != QMessageBox.Yes:
            return
        if not icons_lib.remove_user_icon(fname):
            QMessageBox.warning(self, "失败", "删不掉，文件可能被占用了。")
            return
        it = self._item()
        if it is not None and str(it.get("icon") or "") == fname:
            it["icon"] = ""
            self._save()
        self._reload_icons()
        self._load_item()
        self._set_status(f"已移除 {fname}")

    def _pick_color(self, key, optional):
        it = self._item()
        if it is None:
            return
        cur = str(it.get(key) or "")
        col = QColorDialog.getColor(QColor(cur) if cur else QColor("#141418"),
                                    self, "选择颜色")
        if not col.isValid():
            return
        it[key] = col.name()
        self._paint(self.f[key], col.name(), optional)
        self._save()

    def _paint(self, btn, color, optional=False):
        c = str(color or "").strip()
        if c:
            btn.setText(c)
            btn.setStyleSheet(T.btn_qss("normal", self.alpha) +
                              f"QPushButton {{ background:{c}; color:#ffffff; }}")
        else:
            btn.setText("跟随主题" if optional else "选颜色")
            btn.setStyleSheet(T.btn_qss("normal", self.alpha))

    def _save(self):
        # 只读（看内置预设）时不许落盘 —— 否则「看一眼」就把当前配置写掉了
        if self._is_readonly():
            return
        bar_items.save(self._cfg)
        if callable(self._on_apply):
            self._on_apply()
        self._refresh_preset_hint()
        self._set_status("已保存")

    # ---- 当前配置 / 预设的关系 ----

    def _detect_preset(self):
        """看当前配置和哪套预设一模一样（认不出来就返回空）。

        这样重新打开窗口时也能正确显示「经典」还是「直播间」。

        ⚠ 不能拿 ``bar_items.all_presets()`` 的原始项直接比：
        它是给「套用」用的、字段可能不全，而当前配置是 ``load()`` 出来的、
        每一项都补过默认值。两边字段数不一样，JSON 永不相等 ——
        所以预设那边也要走一遍 ``_fill_item`` 才公平。
        """
        mine = self._norm_cfg(self._cfg)
        for name in bar_items.preset_names():
            p = bar_items.all_presets().get(name)
            if not p:
                continue
            cand = {"window": dict(p.get("window") or bar_items.DEFAULT_WINDOW),
                    "items": [bar_items._fill_item(x)
                              for x in (p.get("items") or [])]}
            if mine == self._norm_cfg(cand):
                return name
        return ""

    @staticmethod
    def _norm_cfg(cfg):
        """比之前先规整：只留窗口设置和各项目的字段，字段顺序无关"""
        win = {k: v for k, v in (cfg.get("window") or {}).items()}
        items = [{k: v for k, v in it.items()} for it in (cfg.get("items") or [])]
        return json.dumps({"window": win, "items": items},
                          sort_keys=True, ensure_ascii=False)

    def _cfg_matches(self, name):
        """当前配置是不是就是这套预设的原样（比之前两边都补默认值）"""
        p = bar_items.all_presets().get(name)
        if not p:
            return False
        cand = {"window": dict(p.get("window") or bar_items.DEFAULT_WINDOW),
                "items": [bar_items._fill_item(x)
                          for x in (p.get("items") or [])]}
        return self._norm_cfg(self._cfg) == self._norm_cfg(cand)

    def _preset_drifted(self):
        """已经偏离当初套用的那套预设了吗"""
        if not self._preset:
            return True
        return not self._cfg_matches(self._preset)

    def _closest_preset(self):
        """当前配置最像哪套预设（项目 id 和窗口排布对得上就算）。

        用来在认不出「完全一样」的时候，告诉用户这套配置是从哪套改出来的。
        """
        ids = tuple(str(x.get("id")) for x in (self._cfg.get("items") or []))
        layout = str((self._cfg.get("window") or {}).get("layout") or "")
        for name in bar_items.preset_names():
            p = bar_items.all_presets().get(name) or {}
            pids = tuple(str(x.get("id")) for x in (p.get("items") or []))
            playout = str((p.get("window") or {}).get("layout") or "")
            if pids and pids == ids and playout == layout:
                return name
        return ""

    def _refresh_preset_hint(self):
        """刷新「当前配置是/偏离哪套预设」的显示。

        界面上的那一行现在在**项目页上方**（``edit_hint``），
        这里只负责把它和项目页里那些勾选框的可用状态一起更新。
        """
        self._refresh_edit_hint()

    def _set_status(self, tail=""):
        """「共 N 个项目，显示 M 个」那行字**已按用户要求删掉**。

        原来它挂在对话框底部，现在底部没有状态栏了。
        其他代码还在调这个方法（导入图标 / 保存 / 取消…），
        所以保留成空实现，别再往界面上写东西。
        """
        return


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
