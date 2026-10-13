# -*- coding: utf-8 -*-
"""直播间挂机 —— 这个模块的**界面卡片**（2026-10-13 从 qt_settings_tabs 搬来）。

接口见 `modules/hang/ui.py` 顶部说明 / `modules/__init__.py`：
主程序不认识"直播间地址""浏览器"这些字段，只管调用本模块的 collect/apply/desc。
删掉整个 `modules/hang/` 文件夹 → 卡片、开关、卸载卡片全都不存在。
"""
from PySide6.QtWidgets import QLineEdit, QVBoxLayout, QWidget

from qt_theme import entry_qss
from qt_widgets import SettingRow, Switch, bind_cb, right_wrap, small_button


def build(tab):
    """造出挂机模块的界面。返回一个 dict（就是"模块 UI 对象"）。"""
    # 模块自己的"装没装"状态 —— 由模块负责，主程序不再替它记
    try:
        import svc_autostart as _A
        tab._hang_installed = _A.mod_on(tab._c, "hang")
    except Exception:
        tab._hang_installed = True
    alpha = tab.alpha
    body = QWidget()
    body.setStyleSheet("background: transparent;")
    lb = QVBoxLayout(body)
    lb.setContentsMargins(0, 0, 0, 0)
    lb.setSpacing(10)
    tab.hang_box = body

    tab.switch_hang = Switch(tab, bool(tab._c.get("hang_enabled", True)))
    tab.switch_hang.toggled.connect(bind_cb(tab._on_hang_mod))
    # 卸载按钮放在**开关左边**（用户 2026-10-13：除 BGI 外所有模块都这样 ✓）
    from PySide6.QtWidgets import QHBoxLayout
    tab.b_uninstall_hang = small_button("卸载", tab._uninstall_hang_clicked,
                                        alpha, icon="trash", kind="danger",
                                        width=84)
    _right = QWidget()
    _right.setStyleSheet("background: transparent;")
    _rl = QHBoxLayout(_right)
    _rl.setContentsMargins(0, 0, 0, 0)
    _rl.setSpacing(8)
    _rl.addWidget(tab.b_uninstall_hang)
    _rl.addWidget(tab.switch_hang)

    tab.row_hang_mod = SettingRow(
        # 简介：由**模块自己**算（desc() 在本文件下面）—— 之前这里是空串，
        # 所以界面上"直播间挂机"没有简介（用户 2026-10-13 反馈）
        tab, "globe", "直播间挂机", desc(tab),
        _right, alpha=alpha,
        tip="**开**：到点用浏览器打开你的直播间页面挂机（选项在下面）。\n"
            "**关**：选项收起来、也不再打开页面。\n"
            "不想留这个模块了 → 点左边的「卸载」按钮，或用页尾的「卸载模块」。")

    # a) 直播间地址
    tab.live_url_entry = QLineEdit(str(tab._c.get("live_url") or ""))
    tab.live_url_entry.setStyleSheet(entry_qss())
    tab.live_url_entry.setMinimumWidth(220)
    tab.live_url_entry.setMaximumWidth(260)
    tab.live_url_entry.setPlaceholderText("https://live.bilibili.com/123456")
    tab.live_url_entry.editingFinished.connect(bind_cb(tab._on_live))
    lb.addWidget(SettingRow(
        body, "globe", "直播间地址",
        "用浏览器打开这个页面挂机（留空则不开）", tab.live_url_entry,
        alpha=alpha,
        tip="填你自己的直播间地址，例如 `https://live.bilibili.com/123456`。\n"
            "会以新窗口打开，不影响你已有的 Chrome 窗口。"))

    # b) 浏览器
    tab.chrome_entry = QLineEdit(str(tab._c.get("chrome_exe") or ""))
    tab.chrome_entry.setStyleSheet(entry_qss())
    tab.chrome_entry.setMinimumWidth(150)
    tab.chrome_entry.setMaximumWidth(240)
    tab.chrome_entry.setPlaceholderText("留空 = 自动探测 Chrome")
    tab.chrome_entry.editingFinished.connect(bind_cb(tab._on_live))
    b_ch = small_button("选择…", tab._pick_chrome, alpha, icon="file-text", width=80)
    b_ch_scan = small_button("探测", tab._detect_chrome_clicked, alpha,
                             icon="search", width=74)
    lb.addWidget(SettingRow(
        body, "monitor", "浏览器",
        "留空则自动探测 Chrome，找不到就用系统默认浏览器",
        right_wrap(tab.chrome_entry, b_ch, b_ch_scan), alpha=alpha,
        tip="想固定用某个浏览器（比如另一个 Chrome 用户数据目录）就在这里指定。"))

    # c) 卸载卡片**已取消** —— 卸载按钮挪到开关左边了（用户 2026-10-13）
    tab.row_uninstall_hang = None
    return {"key": "hang", "box": body, "switch": tab.switch_hang,
            "card": tab.row_hang_mod}


def collect(tab, c):
    """把界面上的值收进配置（挂在 tab 上的控件还是老名字，主程序不用改）"""
    installed = bool(getattr(tab, "_hang_installed", True))
    c["hang_enabled"] = bool(tab.switch_hang.isChecked()) if installed else False
    c["live_url"] = ((tab.live_url_entry.text() or "").strip()
                     if installed else "")
    c["chrome_exe"] = ((tab.chrome_entry.text() or "").strip()
                       if installed else "")


def apply(tab, on):
    """按状态显隐（装没装 + 开关开没开）"""
    installed = bool(getattr(tab, "_hang_installed", True))
    visible = installed and bool(tab.switch_hang.isChecked())
    try:
        tab.hang_box.setVisible(visible)
        tab.row_hang_mod.setVisible(installed)
        if getattr(tab, "row_uninstall_hang", None) is not None:
            tab.row_uninstall_hang.setVisible(installed)
    except Exception:
        pass


def desc(tab):
    """卡片下面那句说明"""
    if not getattr(tab, "_hang_installed", True):
        return "未安装（用页面最下面的「添加模块」装上）"
    if not tab.switch_hang.isChecked():
        return "已安装 · 未启用（打开右侧开关才执行）"
    u = (tab._c.get("live_url") or "").strip()
    return "已安装 · 已启用" + ("　·　" + u if u else "　·　未填直播间地址")
