# -*- coding: utf-8 -*-
"""直播间挂机 —— 这个模块的**界面卡片**（2026-10-13 从 qt_settings_tabs 搬来）。

接口见 `modules/hang/ui.py` 顶部说明 / `modules/__init__.py`：
主程序不认识"直播间地址""浏览器"这些字段，只管调用本模块的 collect/apply/desc。
删掉整个 `modules/hang/` 文件夹 → 卡片、开关、卸载卡片全都不存在。
"""
from PySide6.QtWidgets import QLineEdit, QVBoxLayout, QWidget, QFileDialog

from qt_theme import entry_qss
from qt_widgets import SettingRow, Switch, bind_cb, right_wrap, small_button


def build(tab):
    """造出挂机模块的界面。返回一个 dict（就是"模块 UI 对象"）。"""
    # 模块自己的"装没装"状态 —— 由模块负责，主程序不再替它记
    tab._hang_installed = tab._module_installed("hang")
    alpha = tab.alpha
    body = QWidget()
    body.setStyleSheet("background: transparent;")
    lb = QVBoxLayout(body)
    lb.setContentsMargins(0, 0, 0, 0)
    lb.setSpacing(10)
    tab.hang_box = body

    tab.switch_hang = Switch(
        tab, bool((tab._c.get("modules") or {}).get("hang", True)))
    tab.switch_hang.toggled.connect(
        bind_cb(lambda *_: tab._on_module_toggle(
            "hang", tab.switch_hang.isChecked())))
    # 卸载按钮放在**开关左边**（用户 2026-10-13：除 BGI 外所有模块都这样 ✓）
    from PySide6.QtWidgets import QHBoxLayout
    tab.b_uninstall_hang = small_button(
        "卸载", lambda: tab._do_uninstall_module("hang"),
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
        # 所以界面上"直播间页面"没有简介（用户 2026-10-13 反馈）
        tab, "globe", "直播间页面", desc(tab),
        _right, alpha=alpha,
        tip="启用后按计划打开直播间页面。\n停用后不执行模块动作。\n如需移除模块，请点击“卸载”。")

    # a) 直播间地址
    from modules import load_config
    config = load_config("hang", tab._c)
    tab.live_url_entry = QLineEdit(str(config.get("live_url") or ""))
    tab.live_url_entry.setStyleSheet(entry_qss())
    tab.live_url_entry.setMinimumWidth(220)
    tab.live_url_entry.setMaximumWidth(260)
    tab.live_url_entry.setPlaceholderText("https://live.bilibili.com/123456")
    tab.live_url_entry.editingFinished.connect(bind_cb(lambda: _changed(tab)))
    lb.addWidget(SettingRow(
        body, "globe", "直播间地址",
        "浏览器打开的直播间地址；留空不执行", tab.live_url_entry,
        alpha=alpha,
        tip="输入直播间 URL。将通过新窗口打开，不影响已有浏览器窗口。"))

    # b) 浏览器
    tab.chrome_entry = QLineEdit(str(config.get("chrome_exe") or ""))
    tab.chrome_entry.setStyleSheet(entry_qss())
    tab.chrome_entry.setMinimumWidth(150)
    tab.chrome_entry.setMaximumWidth(240)
    tab.chrome_entry.setPlaceholderText("留空时自动探测")
    tab.chrome_entry.editingFinished.connect(bind_cb(lambda: _changed(tab)))
    b_ch = small_button("选择…", lambda: _pick_chrome(tab), alpha, icon="file-text", width=80)
    b_ch_scan = small_button("探测", lambda: _detect_chrome(tab), alpha,
                             icon="search", width=74)
    lb.addWidget(SettingRow(
        body, "monitor", "浏览器程序",
        "浏览器可执行文件；留空自动探测",
        right_wrap(tab.chrome_entry, b_ch, b_ch_scan), alpha=alpha,
        tip="指定浏览器可执行文件路径；留空自动探测，失败时使用系统默认浏览器。"))

    # c) 卸载卡片**已取消** —— 卸载按钮挪到开关左边了（用户 2026-10-13）
    tab.row_uninstall_hang = None
    return {"key": "hang", "box": body, "switch": tab.switch_hang,
            "card": tab.row_hang_mod}


def collect(tab, c):
    """把挂机模块自己的网址和浏览器设置写入独立配置区。"""
    from modules import save_config
    save_config("hang", c, {
        "live_url": (tab.live_url_entry.text() or "").strip(),
        "chrome_exe": (tab.chrome_entry.text() or "").strip(),
    })


def _changed(tab):
    collect(tab, tab._c)
    tab._on_module_config_changed("hang")


def _pick_chrome(tab):
    p, _ = QFileDialog.getOpenFileName(
        tab._win, "选择浏览器主程序",
        tab.chrome_entry.text().strip() or "C:\\",
        "浏览器 (chrome.exe);;可执行文件 (*.exe)")
    if p:
        tab.chrome_entry.setText(p)
        tab.chrome_entry.setCursorPosition(0)
        _changed(tab)


def _detect_chrome(tab):
    from modules.hang import logic
    p = logic.detect_chrome()
    if p:
        tab.chrome_entry.setText(p)
        tab.chrome_entry.setCursorPosition(0)
        tab._log(f"已定位浏览器：{p}")
    else:
        tab._log("未找到 Chrome，将使用系统默认浏览器。")
    _changed(tab)


def apply(tab, on):
    """按状态显隐（装没装 + 开关开没开）"""
    installed = bool(getattr(tab, "_hang_installed", True))
    tab.switch_hang.blockSignals(True)
    tab.switch_hang.setChecked(bool(on))
    tab.switch_hang.blockSignals(False)
    visible = installed and bool(on) and bool(tab.switch_hang.isChecked())
    try:
        tab.hang_box.setVisible(visible)
        tab.row_hang_mod.setVisible(installed)
        if getattr(tab, "row_uninstall_hang", None) is not None:
            tab.row_uninstall_hang.setVisible(installed)
    except Exception:
        pass
    if getattr(tab, "row_hang_mod", None) is not None:
        tab.row_hang_mod.set_text(desc=desc(tab))


def toggle(tab, on):
    tab._c.setdefault("modules", {})["hang"] = bool(on)
    tab._collect()
    tab._apply_module_visibility()
    tab._save()
    tab._refresh_state()
    tab._log("直播间页面：" + ("已启用" if on else "已停用"))


def reset(tab, config):
    from modules import save_config
    save_config("hang", config, {"live_url": "", "chrome_exe": ""})
    config.setdefault("modules", {})["hang"] = False
    tab.switch_hang.blockSignals(True)
    tab.switch_hang.setChecked(False)
    tab.switch_hang.blockSignals(False)
    tab.live_url_entry.clear()
    tab.chrome_entry.clear()
    if getattr(tab, "row_hang_mod", None) is not None:
        tab.row_hang_mod.set_text(desc=desc(tab))


def desc(tab):
    """卡片下面那句说明"""
    if not getattr(tab, "_hang_installed", True):
        return "未安装：请通过模块管理导入"
    if not tab.switch_hang.isChecked():
        return "已安装 · 未启用"
    from modules import load_config
    config = load_config("hang", tab._c)
    u = (config.get("live_url") or "").strip()
    return "已安装 · 已启用" + ("　·　" + u if u else "　·　未配置直播间地址")
