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
                               QVBoxLayout, QWidget)

import qt_checklist as _ck
from qt_checklist import _box_qss
from qt_theme import ACCENT, entry_qss, label_qss
from qt_widgets import (Accordion, SettingRow, Switch, bind_cb, right_wrap,
                        small_button)

BOX_ORDER = ("row_dir", "row_exe", "row_kill",
             "groups_acc", "mon_acc", "stop_acc")


def desc(tab):
    return "目标程序、连续执行配置组、到点自动监测（关掉则隐藏且不执行）"


# ---------------- BGI 组名（这是 BGI 专属的读取逻辑） ----------------
def bgi_group_names(tab):
    try:
        import svc_autostart as _A
        return _A.bgi_groups((tab._c.get("bgi_dir") or "").strip(),
                             (tab._c.get("bgi_exe") or "").strip())
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
    tab.b_refresh_groups = small_button("刷新组名列表",
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
        tab, "layers", "连续执行配置组", "",
        body_widget=body, alpha=tab.alpha,
        tip="列出 BetterGI 调度器里现有的组（点开勾选）。\n"
            "勾中的组按 BGI 里的顺序依次执行（前一组结束才跑下一组）。\n"
            "一个都不勾 = 只启动程序、不跑任何组。\n"
            "在 BGI 里新建了组 → 点「刷新组名列表」。\n"
            "原理：`BetterGI.exe --startGroups 组1 组2 …`。")
    tab.add_card(tab.groups_acc)
    tab._group_boxes = []
    _refresh_group_names.__get__(tab)  # 只是让它别被优化掉（真正调用在下面）


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
    chosen = list(tab._c.get("groups") or [])
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
            f"已从 BetterGI 读到 {len(names)} 个组，勾选要跑的。"
            if names else
            "没读到 BetterGI 的组名 —— 先确认上面的「程序目录」填对了，"
            "再点「刷新组名列表」。")
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
            (f"{len(g)} 组：" + "　→　".join(g)) if g else "未勾选（不执行任何组）")
    except Exception:
        pass


def _on_groups(tab, *_a):
    tab._bgi_groups_sel = _group_names(tab)
    tab._c["groups"] = tab._bgi_groups_sel
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
    tab.mon_list.set_items(bgi_group_names(tab),
                           [tab._c.get("auto_monitor_group") or ""])
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
    tab.b_refresh_mon = small_button("刷新组名列表",
                                     lambda: _refresh_group_names(tab),
                                     tab.alpha, icon="refresh-cw", width=140)
    tab.b_refresh_mon.setSizePolicy(_QSP.Fixed, _QSP.Fixed)
    ml.addWidget(tab.b_refresh_mon)
    tab.mon_acc = Accordion(
        tab, "triangle-right", "指定配置组启动时开始监测", "",
        body_widget=mb, alpha=tab.alpha,
        tip="展开后勾**一个**配置组：BetterGI 里那个组一开始跑，就自动开始收益监测。\n"
            "不勾 = 不自动开始。")
    tab.add_card(tab.mon_acc)
    tab.row_mon = tab.mon_acc
    tab.switch_mon = None

    # ---------- 指定配置组结束时停止监测 ----------
    tab.stop_list = _ck.CheckList(tab, tab.alpha, mode="single",
                                  on_change=lambda: _on_stop_pick(tab))
    tab.stop_list.set_items(bgi_group_names(tab),
                            [tab._c.get("stop_after_group") or ""])
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
    tab.b_refresh_stop = small_button("刷新组名列表",
                                      lambda: _refresh_group_names(tab),
                                      tab.alpha, icon="refresh-cw", width=140)
    tab.b_refresh_stop.setSizePolicy(_QSP2.Fixed, _QSP2.Fixed)
    sl.addWidget(tab.b_refresh_stop)
    tab.stop_acc = Accordion(
        tab, "square", "指定配置组结束时停止监测", "",
        body_widget=sb, alpha=tab.alpha,
        tip="展开后勾**一个**配置组：那个组一跑完就停止监测并写入记录。\n"
            "不勾 = 不自动停止。\n判断依据是 BetterGI 日志里的「配置组 执行结束」。")
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
            lst.set_items(names, [tab._c.get(key) or ""])
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
            f"已选择「{g1}」配置组，将在「{g1}」启动时开始监测"
            if g1 else "未选择配置组，不自动开始监测")
    except Exception:
        pass
    try:
        g2 = tab.stop_list.value()
        tab.stop_acc.desc_label.setText(
            f"已选择「{g2}」配置组，将在「{g2}」结束时停止监测"
            if g2 else "未选择配置组，不自动停止监测")
    except Exception:
        pass


def _on_mon_pick(tab):
    tab._bgi_mon_group = tab.mon_list.value()
    tab._c["auto_monitor_group"] = tab._bgi_mon_group
    _sync_mon_stop_desc(tab)


def _on_stop_pick(tab):
    tab._bgi_stop_group = tab.stop_list.value()
    tab._c["stop_after_group"] = tab._bgi_stop_group
    _sync_mon_stop_desc(tab)


# ---------------- 程序目录 / 目标程序 / 杀旧BGI ----------------
def _path_rows(tab):
    tab.dir_entry = QLineEdit(str(tab._c.get("bgi_dir") or ""))
    tab.dir_entry.setStyleSheet(entry_qss())
    tab.dir_entry.setMinimumWidth(150)
    tab.dir_entry.setMaximumWidth(240)
    tab.dir_entry.editingFinished.connect(bind_cb(tab._on_paths))
    b_dir = small_button("选择…", tab._pick_dir, tab.alpha,
                         icon="folder-open", width=80)
    tab.row_dir = tab.row("folder-open", "程序目录",
                          "启动前的工作目录；留空则沿用默认",
                          right_wrap(tab.dir_entry, b_dir),
                          tip="启动前的工作目录，一般填 BetterGI 安装目录；留空则沿用默认。")

    tab.exe_entry = QLineEdit(str(tab._c.get("bgi_exe") or ""))
    tab.exe_entry.setStyleSheet(entry_qss())
    tab.exe_entry.setMinimumWidth(150)
    tab.exe_entry.setMaximumWidth(240)
    tab.exe_entry.editingFinished.connect(bind_cb(tab._on_paths))
    b_exe = small_button("选择…", tab._pick_exe, tab.alpha, icon="file-text", width=80)
    b_detect = small_button("探测", tab._detect, tab.alpha, icon="search", width=74)
    tab.row_exe = tab.row("rocket", "目标启动程序",
                          "启动目标；默认 BetterGI.exe，「探测」可自动定位",
                          right_wrap(tab.exe_entry, b_exe, b_detect),
                          tip="启动目标的完整路径。\n默认 BetterGI：启动参数自动"
                              "附加 `--startGroups` 与上方组名。")


def _kill_row(tab):
    tab.switch_kill = Switch(tab, bool(tab._c.get("kill_existing_bgi", True)))
    tab.switch_kill.toggled.connect(bind_cb(tab._on_behavior))
    tab.row_kill = tab.row("x", "强制关闭旧 BGI", "启动前结束已有实例，避免双开冲突",
                           tab.switch_kill,
                           tip="开启后先执行 `taskkill /IM BetterGI.exe /F`，"
                               "等待 5 秒再启动，避免双实例冲突。")


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
    import svc_autostart as _A

    tab.switch_bgi_mod = Switch(tab, _A.mod_on(tab._c, "bgi"))
    tab.switch_bgi_mod.toggled.connect(bind_cb(tab._on_bgi_mod))
    tab.row_bgi_mod = SettingRow(
        tab, "layers", "BetterGI 模块", desc(tab), tab.switch_bgi_mod,
        alpha=tab.alpha,
        tip="**开**：到点启动目标程序（默认 BetterGI）并按顺序执行配置组，"
            "同时可以自动开始/停止收益监测。\n**关**：这些选项整块收起来、也不执行。")

    _path_rows(tab)
    _kill_row(tab)
    _group_card(tab)
    _mon_card(tab)
    # 组名列表要在三张卡都建好之后刷（它会同时刷开始/结束两个单选列表）
    _refresh_group_names(tab)
    _box(tab)

    return {"key": "bgi", "card": tab.row_bgi_mod,
            "box": tab.bgi_box, "switch": tab.switch_bgi_mod}


def collect(tab, c):
    c["groups"] = _group_names(tab)
    return c
