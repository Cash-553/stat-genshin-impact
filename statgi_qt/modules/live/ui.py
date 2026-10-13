# -*- coding: utf-8 -*-
"""直播插件 —— 界面（卡片、卸载按钮、简介都在这里）。

主程序只提供"场地"（页面/显隐/顺序/置顶），**这块长什么样全由本文件决定**。

约定（模块界面的通用契约 —— 主程序只认这三样）：
    build(tab) 返回 {"key", "card", "box", "switch"}
        card   = 开关那张卡片（置顶功能要它）
        box    = 这个模块的选项区（置顶功能要它）
        switch = 开关本身
另外提供 desc(tab)：卡片下面那行简介（每刷新一次问一次 → 跟着状态变）
"""
from PySide6.QtWidgets import QHBoxLayout, QWidget

from qt_widgets import SettingRow, Switch, bind_cb, small_button


def desc(tab):
    """卡片下面那行简介（跟着状态变）"""
    try:
        on = bool(tab._c.get("live_enabled", False))
    except Exception:
        on = False
    if not getattr(tab, "_live_installed", True):
        return "未安装：把模块文件夹放进来即可"
    return "已安装 · " + ("已启用" if on else "未启用（打开右侧开关才执行）")


def build(tab):
    tab._live_installed = tab._module_installed("live")

    tab.switch_live_mod = Switch(tab, bool(tab._c.get("live_enabled", False)))
    tab.switch_live_mod.toggled.connect(bind_cb(tab._on_live_mod))
    # 老名字别名（别的地方还在用）
    tab.switch_live = tab.switch_live_mod

    # ---- 开关 + 卸载按钮：卸载在**开关左边**（用户 2026-10-13 要求）----
    tab.b_uninstall = small_button("卸载", tab._uninstall_live_clicked,
                                   tab.alpha, icon="trash", kind="danger",
                                   width=84)
    right = QWidget()
    right.setStyleSheet("background: transparent;")
    rl = QHBoxLayout(right)
    rl.setContentsMargins(0, 0, 0, 0)
    rl.setSpacing(8)
    rl.addWidget(tab.b_uninstall)
    rl.addWidget(tab.switch_live_mod)

    tab.row_live_mod = SettingRow(
        tab, "camera", "直播插件", desc(tab),
        right, alpha=tab.alpha,
        tip="**开**：到点开 OBS 推流；**关**：选项收起来、也不执行。\n"
            "不想要这个插件了 → 点左边的「卸载」按钮（会清空 OBS 路径等配置）。\n"
            "卸载后可以在页面最下面的「添加模块」里装回来。")

    return {"key": "live", "card": tab.row_live_mod,
            "box": getattr(tab, "live_box", None),
            "switch": tab.switch_live_mod}
