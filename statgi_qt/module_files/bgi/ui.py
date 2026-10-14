# -*- coding: utf-8 -*-
"""BetterGI 模块 —— 界面（**界面内容、样式、简介、回调全在这里**）。

主程序只提供场地：页面、显隐、顺序、滚动置顶、配置收发。

约定：
    build(tab) → {"key", "card", "box", "switch"}
    desc(tab)  → 卡片下面那行简介

本模块的界面包括：
    · 模块卡片（开关 + 简介）
    · 程序目录 / 目标启动程序 / 强制关闭旧BGI
    · 连续执行配置组（多选勾选，勾选的组按 BGI 顺序执行）
    · 指定配置组启动时开始监测（单选）
    · 指定配置组结束时停止监测（单选）
"""
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QLineEdit,
                               QVBoxLayout, QWidget, QFileDialog)

import qt_checklist as _ck
from qt_checklist import _box_qss
from qt_theme import ACCENT, entry_qss, label_qss
from qt_widgets import (Accordion, SettingRow, Switch, bind_cb, right_wrap,
                        small_button)

BOX_ORDER = ("row_dir", "row_exe", "row_kill",
             "groups_acc", "mon_acc", "stop_acc")


def desc(tab):
    return "目标程序、配置组及监测触发规则"


# ---------------- BGI 组名（这是 BGI 专属的读取逻辑） ----------------
def bgi_group_names(tab):
    try:
        from modules.bgi import logic
        config = getattr(tab, "_bgi_config", {})
        return logic.bgi_groups((config.get("bgi_dir") or "").strip(),
                                (config.get("bgi_exe") or "").strip())
    except Exception:
        return []


# ---------------- 连续执行配置组（多选） ----------------
def _group_card(tab):
    body = QWidget()
    body.setStyleSheet("background: transparent;")
    bl = QVBoxLayout(body)
    bl.setContentsMargins(0, 0, 0, 0)
    bl.setSpacing(6)
    tab.groups_lay = QVBoxLayout()
    tab.groups_lay.setContentsMargins(0, 0, 0, 0)
    tab.groups_lay.setSpacing(4)
    bl.addLayout(tab.groups_lay)
    tab.groups_hint = QLabel("")
    tab.groups_hint.setWordWrap(True)
    tab.groups_hint.setStyleSheet(label_qss(_dim(), 11))
    bl.addWidget(tab.groups_hint)
    tab.b_refresh_groups = small_button("刷新配置组",
                                        lambda: _refresh_group_names(tab),
                                        tab.alpha, icon="refresh-cw", width=140)
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QSizePolicy
    tab.b_refresh_groups.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    # ⚠ 别传对齐参数（Qt.AlignLeft）：折叠卡搬内容时会把带对齐的那个按钮销毁 ✗
    #   后果就是"刷新按钮点不动/对象已删除"（用户 2026-10-13 反馈）✓
    tab.b_refresh_groups.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    bl.addWidget(tab.b_refresh_groups)
    tab.groups_acc = Accordion(
        tab, "layers", "执行配置组", "",
        body_widget=body, alpha=tab.alpha,
        tip="读取 BetterGI 配置组并选择执行项。\n"
            "所选配置组按顺序执行。\n"
            "未选择配置组时，仅启动目标程序。\n"
            "新增配置组后，请点击“刷新配置组”。")
    tab.add_card(tab.groups_acc)
    tab._group_boxes = []


def _dim():
    try:
        import qt_theme as _T
        return _T.DIM
    except Exception:
        return "#8b9096"


def _refresh_group_names(tab_or_self=None, *_a):
    """把 BGI 的组全列成勾选框（保留已勾的）—— 绑定到 tab 上调用"""
    tab = tab_or_self
    names = bgi_group_names(tab)
    bgi_config = getattr(tab, "_bgi_config", {})
    chosen = list(bgi_config.get("groups") or [])
    while tab.groups_lay.count():
        it = tab.groups_lay.takeAt(0)
        w = it.widget()
        if w is not None:
            w.setParent(None)
            try:
                w.deleteLater()
            except Exception:
                pass
    tab._group_boxes = []
    for n in list(names) + [n for n in chosen if n not in names]:
        box = QCheckBox(n + ("" if n in names else "\u3000（BetterGI 里没找到）"))
        try:
            box.setStyleSheet(_box_qss(ACCENT))
        except Exception:
            pass
        box.setChecked(n in chosen)
        box.toggled.connect(lambda _c: _on_groups(tab))
        tab.groups_lay.addWidget(box)
        tab._group_boxes.append((n, box))
    try:
        tab.groups_hint.setText(
            f"已读取 {len(names)} 个配置组，请选择执行项。"
            if names else
            "未读取到配置组，请检查程序目录后刷新。")
    except Exception:
        pass
    _sync_groups_desc(tab)
    # ⚠ 2026-10-13：两个监测卡（单选列表）也要一起刷新
    #   它们原来只在建界面时填过一次 → BGI 目录是后来才探测到的 → 点开是空的
    refresh_mon_stop(tab)


def _group_names(tab):
    return [n for (n, b) in getattr(tab, "_group_boxes", []) if b.isChecked()]


def _sync_groups_desc(tab):
    g = _group_names(tab)
    try:
        tab.groups_acc.desc_label.setText(
            (f"已选择 {len(g)} 组：" + "　→　".join(g)) if g else "未选择配置组")
    except Exception:
        pass


def _on_groups(tab, *_a):
    tab._bgi_groups_sel = _group_names(tab)
    tab._bgi_config["groups"] = tab._bgi_groups_sel
    _sync_groups_desc(tab)


# ---------------- 开始 / 结束监测（单选） ----------------
def _mon_card(tab):
    """开始 / 结束监测两张卡。

    ⚠ 折叠卡创建时就把内容拆走 ✗，且只认"容器 → 一层布局 → 勾选框"✓
      所以这里：先建勾选框 → 搬进一层布局 → 再建折叠卡 ✓
      （配置组那张卡就是这个形状 ✓）
    """
    # ---------- 指定配置组启动时开始监测 ----------
    tab.mon_list = _ck.CheckList(tab, tab.alpha, mode="single",
                                 on_change=lambda: _on_mon_pick(tab))
    bgi_config = getattr(tab, "_bgi_config", {})
    tab.mon_list.set_items(bgi_group_names(tab),
                           [bgi_config.get("auto_monitor_group") or ""])
    tab.mon_lay = QVBoxLayout()
    tab.mon_lay.setContentsMargins(0, 0, 0, 0)
    tab.mon_lay.setSpacing(4)
    for _n, _b in tab.mon_list.boxes:
        tab.mon_lay.addWidget(_b)
    mb = QWidget()
    mb.setStyleSheet("background: transparent;")
    ml = QVBoxLayout(mb)
    ml.setContentsMargins(0, 0, 0, 0)
    ml.setSpacing(6)
    ml.addLayout(tab.mon_lay)
    # 刷新按钮（用户 2026-10-13：这两张卡也要能刷新组名列表 ✓）
    from PySide6.QtWidgets import QSizePolicy as _QSP
    tab.b_refresh_mon = small_button("刷新配置组",
                                     lambda: _refresh_group_names(tab),
                                     tab.alpha, icon="refresh-cw", width=140)
    tab.b_refresh_mon.setSizePolicy(_QSP.Fixed, _QSP.Fixed)
    ml.addWidget(tab.b_refresh_mon)
    tab.mon_acc = Accordion(
        tab, "triangle-right", "启动配置组时开始监测", "",
        body_widget=mb, alpha=tab.alpha,
        tip="选择一个配置组；该组启动时开始收益监测。\n未选择时不自动开始监测。")
    tab.add_card(tab.mon_acc)
    tab.row_mon = tab.mon_acc
    tab.switch_mon = None

    # ---------- 指定配置组结束时停止监测 ----------
    tab.stop_list = _ck.CheckList(tab, tab.alpha, mode="single",
                                  on_change=lambda: _on_stop_pick(tab))
    tab.stop_list.set_items(bgi_group_names(tab),
                            [bgi_config.get("stop_after_group") or ""])
    tab.stop_lay = QVBoxLayout()
    tab.stop_lay.setContentsMargins(0, 0, 0, 0)
    tab.stop_lay.setSpacing(4)
    for _n, _b in tab.stop_list.boxes:
        tab.stop_lay.addWidget(_b)
    sb = QWidget()
    sb.setStyleSheet("background: transparent;")
    sl = QVBoxLayout(sb)
    sl.setContentsMargins(0, 0, 0, 0)
    sl.setSpacing(6)
    sl.addLayout(tab.stop_lay)
    from PySide6.QtWidgets import QSizePolicy as _QSP2
    tab.b_refresh_stop = small_button("刷新配置组",
                                      lambda: _refresh_group_names(tab),
                                      tab.alpha, icon="refresh-cw", width=140)
    tab.b_refresh_stop.setSizePolicy(_QSP2.Fixed, _QSP2.Fixed)
    sl.addWidget(tab.b_refresh_stop)
    tab.stop_acc = Accordion(
        tab, "square", "配置组完成后停止监测", "",
        body_widget=sb, alpha=tab.alpha,
        tip="选择一个配置组；该组完成后停止监测并写入记录。\n未选择时不自动停止监测。")
    tab.add_card(tab.stop_acc)
    tab.row_stop = tab.stop_acc
    tab.switch_stop = None
    _sync_mon_stop_desc(tab)

def refresh_mon_stop(tab, *_a):
    """重新读组名，刷新两个单选列表（点「刷新组名列表」时也会走到这）"""
    names = bgi_group_names(tab)
    for lst, lay, key, attr in (
            (getattr(tab, "mon_list", None), getattr(tab, "mon_lay", None),
             "auto_monitor_group", "_bgi_mon_group"),
            (getattr(tab, "stop_list", None), getattr(tab, "stop_lay", None),
             "stop_after_group", "_bgi_stop_group")):
        if lst is None or lay is None:
            continue
        try:
            bgi_config = getattr(tab, "_bgi_config", {})
            lst.set_items(names, [bgi_config.get(key) or ""])
            while lay.count():
                it = lay.takeAt(0)
                w = it.widget()
                if w is not None:
                    w.setParent(None)
            for _n, _b in lst.boxes:
                lay.addWidget(_b)
            setattr(tab, attr, lst.value())
        except Exception:
            pass
    _sync_mon_stop_desc(tab)

def _sync_mon_stop_desc(tab):
    try:
        g1 = tab.mon_list.value()
        tab.mon_acc.desc_label.setText(
            f"已选择「{g1}」，启动时开始监测"
            if g1 else "未选择配置组")
    except Exception:
        pass
    try:
        g2 = tab.stop_list.value()
        tab.stop_acc.desc_label.setText(
            f"已选择「{g2}」，完成后停止监测"
            if g2 else "未选择配置组")
    except Exception:
        pass


def _on_mon_pick(tab):
    tab._bgi_mon_group = tab.mon_list.value()
    tab._bgi_config["auto_monitor_group"] = tab._bgi_mon_group
    _sync_mon_stop_desc(tab)


def _on_stop_pick(tab):
    tab._bgi_stop_group = tab.stop_list.value()
    tab._bgi_config["stop_after_group"] = tab._bgi_stop_group
    _sync_mon_stop_desc(tab)


# ---------------- 程序目录 / 目标程序 / 杀旧BGI ----------------
def _path_rows(tab):
    config = getattr(tab, "_bgi_config", {})
    tab.dir_entry = QLineEdit(str(config.get("bgi_dir") or ""))
    tab.dir_entry.setStyleSheet(entry_qss())
    tab.dir_entry.setMinimumWidth(150)
    tab.dir_entry.setMaximumWidth(240)
    tab.dir_entry.editingFinished.connect(bind_cb(lambda: _on_change(tab)))
    b_dir = small_button("选择…", lambda: _pick_dir(tab), tab.alpha,
                         icon="folder-open", width=80)
    tab.row_dir = tab.row("folder-open", "工作目录",
                          "BetterGI 工作目录；留空使用默认目录",
                          right_wrap(tab.dir_entry, b_dir),
                          tip="BetterGI 工作目录。留空使用默认目录。")

    tab.exe_entry = QLineEdit(str(config.get("bgi_exe") or ""))
    tab.exe_entry.setStyleSheet(entry_qss())
    tab.exe_entry.setMinimumWidth(150)
    tab.exe_entry.setMaximumWidth(240)
    tab.exe_entry.editingFinished.connect(bind_cb(lambda: _on_change(tab)))
    b_exe = small_button("选择…", lambda: _pick_exe(tab), tab.alpha, icon="file-text", width=80)
    b_detect = small_button("探测", lambda: _detect(tab), tab.alpha, icon="search", width=74)
    tab.row_exe = tab.row("rocket", "目标程序",
                          "BetterGI 可执行文件；支持自动探测",
                          right_wrap(tab.exe_entry, b_exe, b_detect),
                          tip="指定 BetterGI.exe 完整路径。\n启动时自动附加所选配置组参数。")


def _kill_row(tab):
    config = getattr(tab, "_bgi_config", {})
    tab.switch_kill = Switch(tab, bool(config.get("kill_existing_bgi", True)))
    tab.switch_kill.toggled.connect(bind_cb(lambda: _on_change(tab)))
    tab.row_kill = tab.row("x", "启动前关闭旧实例", "启动前关闭已有 BetterGI 实例",
                           tab.switch_kill,
                           tip="启用后在启动前终止 BetterGI.exe，避免多实例冲突。")


def _box(tab):
    body = QWidget()
    body.setStyleSheet("background: transparent;")
    bl = QVBoxLayout(body)
    bl.setContentsMargins(0, 0, 0, 0)
    bl.setSpacing(6)
    for name in BOX_ORDER:
        w = getattr(tab, name, None)
        if w is not None:
            bl.addWidget(w)
    tab.bgi_box = body
    tab.bgi_acc = body
    tab.add_card(body)


def build(tab):
    from modules import load_config
    bgi_config = load_config("bgi", tab._c)
    tab._bgi_config = dict(bgi_config)
    tab.switch_bgi_mod = Switch(
        tab, bool((tab._c.get("modules") or {}).get("bgi", True)))
    tab.switch_bgi_mod.toggled.connect(
        bind_cb(lambda *_: tab._on_module_toggle(
            "bgi", tab.switch_bgi_mod.isChecked())))
    tab.row_bgi_mod = SettingRow(
        tab, "layers", "BetterGI 模块", desc(tab), tab.switch_bgi_mod,
        alpha=tab.alpha,
        tip="启用后按计划启动 BetterGI，并执行所选配置组及监测规则。\n停用后不执行模块动作。")

    _path_rows(tab)
    _kill_row(tab)
    _group_card(tab)
    _mon_card(tab)
    # 组名列表要在三张卡都建好之后刷（它会同时刷开始/结束两个单选列表）
    _refresh_group_names(tab)
    _box(tab)

    return {"key": "bgi", "card": tab.row_bgi_mod,
            "box": tab.bgi_box, "switch": tab.switch_bgi_mod}


def apply(tab, on):
    tab.switch_bgi_mod.blockSignals(True)
    tab.switch_bgi_mod.setChecked(bool(on))
    tab.switch_bgi_mod.blockSignals(False)
    tab.bgi_box.setVisible(bool(on))
    for name in ("row_mon", "row_stop"):
        row = getattr(tab, name, None)
        if row is not None:
            row.setVisible(bool(on))
    tab.row_bgi_mod.set_text(
        desc=("目标程序、配置组及监测触发规则" if on else "已停用"))


def toggle(tab, on):
    tab._c.setdefault("modules", {})["bgi"] = bool(on)
    tab._collect()
    tab._apply_module_visibility()
    tab._save()
    tab._refresh_state()
    tab._log("BetterGI 模块：" + ("已启用" if on else "已停用"))


def reset(tab, config):
    """恢复模块自身设置默认值；模块本体仍保留，可再次启用。"""
    defaults = {
        "bgi_dir": "", "bgi_exe": "", "groups": [],
        "kill_existing_bgi": True, "auto_monitor_group": "",
        "stop_after_group": "",
    }
    from modules import save_config
    save_config("bgi", config, defaults)
    for key in defaults:
        config.pop(key, None)
    for widget in (getattr(tab, "switch_bgi_mod", None),
                   getattr(tab, "switch_kill", None)):
        if widget is not None:
            widget.blockSignals(True)
    tab.switch_bgi_mod.setChecked(False)
    tab.switch_kill.setChecked(True)
    tab.dir_entry.clear()
    tab.exe_entry.clear()
    for _name, checkbox in getattr(tab, "_group_boxes", []):
        checkbox.setChecked(False)
    tab._bgi_config = dict(defaults)
    for widget in (getattr(tab, "switch_bgi_mod", None),
                   getattr(tab, "switch_kill", None)):
        if widget is not None:
            widget.blockSignals(False)


def collect(tab, c):
    from modules.bgi import logic
    from modules import load_config, save_config
    result = logic.collect_ui(tab, c)
    config = load_config("bgi", c)
    for key in ("bgi_dir", "bgi_exe", "groups", "kill_existing_bgi",
                "auto_monitor_group", "stop_after_group"):
        if key in result:
            config[key] = result[key]
            c.pop(key, None)
    save_config("bgi", c, config)
    tab._bgi_config = dict(config)
    return c


def _on_change(tab):
    collect(tab, tab._c)
    tab._save()
    tab._refresh_state()


def _pick_dir(tab):
    d = QFileDialog.getExistingDirectory(
        tab._win, "选择程序目录", tab.dir_entry.text().strip() or "D:\\")
    if d:
        tab.dir_entry.setText(d)
        _on_change(tab)
        _refresh_group_names(tab)


def _pick_exe(tab):
    f, _ = QFileDialog.getOpenFileName(
        tab._win, "选择要启动的程序",
        tab.dir_entry.text().strip() or "D:\\", "程序 (*.exe)")
    if f:
        tab.exe_entry.setText(f)
        if not tab.dir_entry.text().strip():
            from pathlib import Path
            tab.dir_entry.setText(str(Path(f).parent))
        _on_change(tab)
        _refresh_group_names(tab)


def _detect(tab):
    from modules.bgi import logic
    directory, exe = logic.detect_bgi()
    if exe:
        tab.dir_entry.setText(directory)
        tab.exe_entry.setText(exe)
        _on_change(tab)
        _refresh_group_names(tab)
        tab._log(f"已定位：{exe}")
    else:
        tab._log("未在常见位置找到 BetterGI，请手动指定。")


def tools(tab):
    """本模块提供的可选工具按钮；页面不需要知道它们的具体含义。"""
    return [("查看 BetterGI 日志", lambda: _show_log(tab))]


def module_tools(tab):
    """可选的模块专属操作按钮。"""
    return tools(tab)


def _show_log(tab):
    from PySide6.QtWidgets import QPlainTextEdit
    from qt_dlg_card import CardDialog
    from qt_theme import entry_qss
    from qt_widgets import small_button
    from modules.bgi import logic

    from modules import load_config
    bgi = load_config("bgi", tab._c)
    path = logic.latest_bgi_log(bgi.get("bgi_dir", ""),
                                bgi.get("bgi_exe", ""))
    if not path:
        tab._log("没找到 BetterGI 的日志（检查模块里的程序目录设置）。")
        return
    dlg = CardDialog(tab._win, tab.alpha, title="BetterGI 日志", width=460)
    dlg.set_subtitle(str(path).split("\\")[-1])
    editor = QPlainTextEdit(logic.tail_text(path, lines=200))
    editor.setReadOnly(True)
    editor.setFixedHeight(300)
    editor.setStyleSheet(entry_qss())
    dlg.add_widget(editor)
    button = small_button("用记事本打开", lambda: _open_log(tab, path),
                          tab.alpha, icon="file-text", width=130)
    dlg.add_widget(button)
    dlg.add_confirm("关闭")
    dlg.exec()


def _open_log(tab, path):
    import os
    try:
        os.startfile(str(path))
    except Exception as exc:
        tab._log(f"打开日志失败：{exc}")
