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
from PySide6.QtWidgets import (QHBoxLayout, QLineEdit, QFileDialog, QWidget,
                               QVBoxLayout)
from PySide6.QtCore import Qt
from copy import deepcopy

from qt_theme import entry_qss
from qt_widgets import (SettingRow, Switch, bind_cb, right_wrap,
                        small_button)


def desc(tab):
    """卡片下面那行简介（跟着状态变）"""
    if not getattr(tab, "_live_installed", True):
        return "未安装：请通过模块管理导入"
    on = bool((tab._c.get("modules") or {}).get("live", True))
    from modules import load_config
    config = load_config("live", tab._c)
    exe = str(config.get("obs_exe") or "").strip()
    return ("已安装 · " + ("已启用" if on else "未启用")
            + (f" · {exe}" if exe else " · OBS 路径自动探测"))


def build(tab):
    tab._live_installed = tab._module_installed("live")
    alpha = tab.alpha
    body = QWidget()
    body.setStyleSheet("background: transparent;")
    layout = QVBoxLayout(body)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)
    tab.live_box = body

    tab.switch_live_mod = Switch(
        tab, bool((tab._c.get("modules") or {}).get("live", True)))
    tab.switch_live_mod.toggled.connect(
        bind_cb(lambda *_: tab._on_module_toggle(
            "live", tab.switch_live_mod.isChecked())))
    # 老名字别名（别的地方还在用）

    # ---- 开关 + 卸载按钮：卸载在**开关左边**（用户 2026-10-13 要求）----
    tab.b_uninstall = small_button("卸载", lambda: tab._do_uninstall_module("live"),
                                   alpha, icon="trash", kind="danger",
                                   width=84)
    right = QWidget()
    right.setStyleSheet("background: transparent;")
    rl = QHBoxLayout(right)
    rl.setContentsMargins(0, 0, 0, 0)
    rl.setSpacing(8)
    rl.addWidget(tab.b_uninstall)
    rl.addWidget(tab.switch_live_mod)

    tab.row_live_mod = SettingRow(
        tab, "camera", "OBS 推流", desc(tab),
        right, alpha=alpha,
        tip="启用后按计划启动 OBS 并执行推流配置。\n停用后不执行模块动作。\n如需移除模块，请点击“卸载”。")

    from modules import load_config
    config = load_config("live", tab._c)
    tab.obs_entry = _path_entry(tab, "obs_exe", "obs64.exe；留空自动探测", config)
    b_obs = small_button("选择…", lambda: _pick_exe(tab), alpha,
                         icon="file-text", width=80)
    b_scan = small_button("探测", lambda: _detect_obs(tab), alpha,
                          icon="search", width=74)
    layout.addWidget(SettingRow(
        body, "file-text", "OBS 程序", "OBS 程序路径；留空自动探测",
        right_wrap(tab.obs_entry, b_obs, b_scan), alpha=alpha))

    tab.switch_steam = Switch(tab, bool(config.get("obs_via_steam", False)))
    tab.switch_steam.toggled.connect(bind_cb(lambda: _changed(tab)))
    layout.addWidget(SettingRow(body, "plug", "Steam 启动模式",
                                "Steam 版 OBS 适用",
                                tab.switch_steam, alpha=alpha))
    tab.switch_obs_stream = Switch(
        tab, bool(config.get("obs_start_stream", True)))
    tab.switch_obs_stream.toggled.connect(bind_cb(lambda: _changed(tab)))
    layout.addWidget(SettingRow(body, "radio", "自动开始推流",
                                "启动 OBS 后自动开始推流",
                                tab.switch_obs_stream, alpha=alpha))
    tab.switch_obs_min = Switch(tab, bool(config.get("obs_minimize", True)))
    tab.switch_obs_min.toggled.connect(bind_cb(lambda: _changed(tab)))
    layout.addWidget(SettingRow(body, "minus", "启动后最小化到托盘",
                                "启动 OBS 后最小化至系统托盘",
                                tab.switch_obs_min, alpha=alpha))
    tab.live_delay_entry = QLineEdit(str(config.get("live_delay") or 0))
    tab.live_delay_entry.setStyleSheet(entry_qss())
    tab.live_delay_entry.setFixedWidth(70)
    tab.live_delay_entry.setAlignment(Qt.AlignCenter)
    tab.live_delay_entry.editingFinished.connect(bind_cb(lambda: _changed(tab)))
    layout.addWidget(SettingRow(body, "clock", "启动延迟", "OBS 启动后等待时间（秒）",
                                tab.live_delay_entry, alpha=alpha))
    b_test = small_button("测试推流动作", lambda: test(tab), alpha,
                          icon="play", width=120)
    layout.addWidget(right_wrap(b_test))
    return {"key": "live", "card": tab.row_live_mod,
            "box": body, "switch": tab.switch_live_mod}


def _path_entry(tab, key, placeholder, config):
    entry = QLineEdit(str(config.get(key) or ""))
    entry.setStyleSheet(entry_qss())
    entry.setMinimumWidth(150)
    entry.setMaximumWidth(240)
    entry.setPlaceholderText(placeholder)
    entry.editingFinished.connect(bind_cb(lambda: _changed(tab)))
    return entry


def _pick_exe(tab):
    p, _ = QFileDialog.getOpenFileName(
        tab._win, "选择 OBS 主程序（obs64.exe）",
        tab.obs_entry.text().strip() or "C:\\",
        "OBS 主程序 (obs64.exe);;可执行文件 (*.exe)")
    if p:
        tab.obs_entry.setText(p)
        tab.obs_entry.setCursorPosition(0)
        _changed(tab)


def _detect_obs(tab):
    from modules.live import logic
    p = logic.detect_obs()
    if p:
        tab.obs_entry.setText(p)
        tab.obs_entry.setCursorPosition(0)
        tab._log(f"已定位 OBS：{p}")
    else:
        tab._log("未在常见位置找到 OBS，请手动指定 obs64.exe。")
    _changed(tab)


def collect(tab, c):
    from modules import load_config, save_config
    config = load_config("live", c)
    config["obs_exe"] = tab.obs_entry.text().strip()
    config["obs_via_steam"] = bool(tab.switch_steam.isChecked())
    config["obs_start_stream"] = bool(tab.switch_obs_stream.isChecked())
    config["obs_minimize"] = bool(tab.switch_obs_min.isChecked())
    try:
        config["live_delay"] = max(0, int(tab.live_delay_entry.text().strip() or "0"))
    except ValueError:
        config["live_delay"] = 0
    save_config("live", c, config)


def _changed(tab):
    collect(tab, tab._c)
    tab._on_module_config_changed("live")


def apply(tab, on):
    installed = bool(getattr(tab, "_live_installed", False))
    tab.switch_live_mod.blockSignals(True)
    tab.switch_live_mod.setChecked(bool(on))
    tab.switch_live_mod.blockSignals(False)
    tab.row_live_mod.setVisible(installed)
    tab.live_box.setVisible(installed and bool(on)
                            and tab.switch_live_mod.isChecked())
    tab.row_live_mod.set_text(desc=desc(tab))


def toggle(tab, on):
    tab._c.setdefault("modules", {})["live"] = bool(on)
    tab._collect()
    tab._apply_module_visibility()
    tab._save()
    tab._refresh_state()
    tab._log("OBS 推流：" + ("已启用" if on else "已停用"))


def reset(tab, config):
    from modules import save_config
    save_config("live", config, {
        "obs_exe": "", "obs_via_steam": False,
        "obs_start_stream": True, "obs_minimize": True, "live_delay": 0,
    })
    config.setdefault("modules", {})["live"] = False
    for widget in (tab.switch_live_mod, tab.switch_steam,
                   tab.switch_obs_stream, tab.switch_obs_min):
        widget.blockSignals(True)
    tab.switch_live_mod.setChecked(False)
    tab.obs_entry.clear()
    tab.switch_steam.setChecked(False)
    tab.switch_obs_stream.setChecked(True)
    tab.switch_obs_min.setChecked(True)
    tab.live_delay_entry.setText("0")
    for widget in (tab.switch_live_mod, tab.switch_steam,
                   tab.switch_obs_stream, tab.switch_obs_min):
        widget.blockSignals(False)
    tab.row_live_mod.set_text(desc=desc(tab))


def test(tab):
    collect(tab, tab._c)
    test_config = deepcopy(tab._c)
    test_config.setdefault("modules", {})["live"] = True
    notes = __import__("svc_autostart").module_steps(test_config, "live")
    notes = __import__("svc_autostart").run_steps(notes)
    tab._log("推流测试：" + ("；".join(notes) if notes else "未配置动作"))
