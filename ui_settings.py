# -*- coding: utf-8 -*-
"""设置的读写、各项设置的回调、开发者选项（AI 样本采集）。

原则：**改完立即生效、立即存盘，没有「保存」按钮**。
所以每个控件的 command 基本都指向 _on_any_setting_change，
它负责：读控件 -> 写 settings -> 存文件 -> 同步给检测器 -> 该刷的刷一遍。"""
from pathlib import Path
from tkinter import messagebox, filedialog, colorchooser

import theme
import config_manager
from ui_base import (
    BG, ACCENT, DIM, GOOD, _keysym_to_vk, _hotkey_name,
)



class SettingsMixin:
    def _on_bar_opacity_change(self, value):
        """统计条透明度滑块：立即预览 + 延迟保存（避免拖动时频繁写文件）"""
        try:
            v = max(0.2, min(1.0, float(value)))
            bar = dict(self.settings.get("stat_bar") or {})
            bar["opacity"] = round(v, 2)
            self.settings["stat_bar"] = bar
            try:
                self.bar_opacity_label.configure(text=f"{int(round(v * 100))}%")
            except Exception:
                pass
            # 统计条已打开 → 立刻生效
            if self.stat_bar is not None:
                try:
                    if self.stat_bar.winfo_exists():
                        self.stat_bar.apply_appearance()
                except Exception:
                    pass
            # 延迟保存
            if getattr(self, "_bar_op_after", None):
                try:
                    self.after_cancel(self._bar_op_after)
                except Exception:
                    pass
            self._bar_op_after = self.after(
                400, lambda: config_manager.save_settings(self.settings))
        except Exception:
            pass

    def _on_panel_opacity_change(self, value):
        """卡片透明度滑块：拖动时实时预览，停一下再写文件"""
        try:
            pct = int(round(float(value)))
            self.settings["panel_opacity"] = round(pct / 100.0, 3)
            self.opacity_label.configure(text=f"{pct}%")
        except Exception:
            pass
        try:
            if getattr(self, "_op_after", None):
                try:
                    self.after_cancel(self._op_after)
                except Exception:
                    pass
            self._op_after = self.after(110, self._on_any_setting_change)
        except Exception:
            pass

    def _on_bg_dim_change(self, value):
        """背景压暗滑块：拖动时实时预览，停一下再写文件"""
        try:
            pct = int(round(float(value)))
            self.settings["bg_dim"] = round(pct / 100.0, 3)
            self.dim_label.configure(text=f"{pct}%")
        except Exception:
            pass
        try:
            if getattr(self, "_dim_after", None):
                try:
                    self.after_cancel(self._dim_after)
                except Exception:
                    pass
            self._dim_after = self.after(110, self._on_any_setting_change)
        except Exception:
            pass

    def _start_hotkey_capture(self):
        """点按钮后，等待用户按下一个键组合"""
        if getattr(self, "_capturing_hotkey", False):
            return
        self._capturing_hotkey = True
        try:
            self.hotkey_btn.configure(text="请按下按键…（Esc 取消）")
            self.bind_all("<KeyPress>", self._on_hotkey_key, add="+")
        except Exception:
            self._capturing_hotkey = False

    def _refresh_hotkey_btn(self):
        try:
            self.hotkey_btn.configure(text=str(self.settings.get("hotkey", "关闭")))
        except Exception:
            pass

    def _on_hotkey_key(self, event):
        if not getattr(self, "_capturing_hotkey", False):
            return
        self._capturing_hotkey = False
        try:
            self.unbind_all("<KeyPress>")
        except Exception:
            pass
        ks = (event.keysym or "").upper()
        if ks in ("ESCAPE",):
            self._refresh_hotkey_btn()
            return
        vk = _keysym_to_vk(ks)
        if vk is None:
            try:
                self.hotkey_btn.configure(text="这个键不支持，请重试")
            except Exception:
                pass
            self.after(1200, self._refresh_hotkey_btn)
            return
        st = int(getattr(event, "state", 0) or 0)
        mods = 0
        if st & 0x0004:
            mods |= 0x0002            # Ctrl
        if st & (0x0008 | 0x00020000):
            mods |= 0x0001            # Alt
        if st & 0x0001:
            mods |= 0x0004            # Shift
        name = _hotkey_name(mods, ks)
        self.settings["hotkey"] = name
        try:
            self.hotkey_var.set(name)
            self.hotkey_btn.configure(text=name)
        except Exception:
            pass
        try:
            self._apply_hotkey()
            config_manager.save_settings(self.settings)
        except Exception:
            pass

    def _dev_path_display(self):
        p = self.settings.get("dataset_path") or ""
        if p:
            return p
        from dataset_collector import DEFAULT_PATH
        return str(DEFAULT_PATH)

    def _dev_collector(self):
        return DatasetCollector(self.settings)

    def _refresh_dev_stats(self):
        """统计样本数量。

        扫描上千个文件很慢（约 0.5 秒），所以放到后台线程算，
        算完由主循环取回来显示，界面完全不卡。
        """
        if getattr(self, "_dev_stats_busy", False):
            return
        self._dev_stats_busy = True

        def _work():
            try:
                s = DatasetCollector(self.settings).stats()
            except Exception:
                s = None
            self._dev_stats_result = s if s else {}   # 后台线程写，主循环读

        try:
            threading.Thread(target=_work, daemon=True).start()
        except Exception:
            self._dev_stats_busy = False
            self._dev_stats_result = None

    def _apply_dev_stats(self):
        """把后台算好的样本统计显示出来（主线程调用）"""
        r = getattr(self, "_dev_stats_result", None)
        if r is None:
            return
        self._dev_stats_result = None
        self._dev_stats_busy = False
        if not r:
            return
        try:
            if hasattr(self, "_dev_stats_label"):
                self._dev_stats_label.configure(
                    text=f"GAMEPLAY：{r.get('gameplay', 0)}    "
                         f"NON_GAMEPLAY：{r.get('non_gameplay', 0)}\n"
                         f"总样本：{r.get('total', 0)}    "
                         f"占用：{r.get('size_mb', 0)} MB / {r.get('max_mb', 100)} MB"
                )
        except Exception:
            pass

    def _on_choose_dataset_path(self):
        p = filedialog.askdirectory(title="选择样本保存目录", initialdir=self._dev_path_display())
        if not p:
            return
        # 检查是否在项目目录内
        try:
            proj = str(Path(__file__).resolve().parent)
            if proj in p:
                if not messagebox.askyesno("警告", "⚠️ 当前样本保存目录位于 StatGI 项目目录中。\n"
                                                 "这些截图可能被 Git 跟踪或误提交到 GitHub。\n"
                                                 "建议选择项目目录之外的位置。\n\n是否仍然使用？"):
                    return
        except Exception:
            pass
        self.settings["dataset_path"] = p
        self._dataset_path_label.configure(text=p)
        self._refresh_dev_stats()

    def _on_manual_capture(self, label):
        try:
            if self.detector is not None:
                frame = self.detector._grab()
                self._dev_collector().capture_manual(frame, label)
                self.after(500, self._refresh_dev_stats)
                messagebox.showinfo("已采集", f"已触发 {label} 样本采集（后台处理）。")
            else:
                messagebox.showinfo("提示", "请先开始监测，才能采集画面。")
        except Exception as e:
            messagebox.showerror("失败", f"采集失败：{e}")

    def _open_data_dir(self):
        """打开程序旁边的 data 文件夹（托盘菜单用）"""
        import os
        try:
            from paths import app_dir
            d = app_dir() / "data"
            d.mkdir(parents=True, exist_ok=True)
            os.startfile(str(d))
        except Exception:
            pass

    def _on_open_dataset(self):
        import os
        try:
            os.startfile(self._dev_path_display())
        except Exception as e:
            messagebox.showerror("失败", f"无法打开文件夹：{e}")

    def _on_clear_dataset(self):
        if not messagebox.askyesno("确认", "确定要删除所有本地 AI 样本吗？\n\n此操作无法恢复。\n\n[取消] / [确认删除]"):
            return
        ok = self._dev_collector().clear_all()
        self._refresh_dev_stats()
        messagebox.showinfo("已清空", "本地 AI 样本已清空。" if ok else "清空失败。")

    def _on_pick_bg_color(self, value):
        """背景颜色：选预设直接生效；选「自定义…」打开取色器（取消则回到之前选的）"""
        if value != "自定义…":
            self._last_bg_sel = value
            self._on_any_setting_change()
            return
        back = getattr(self, "_last_bg_sel", "经典深黑")
        c = colorchooser.askcolor(title="选择背景颜色", color=BG)[1]
        if c:
            self._custom_bg_hex = c
            self._on_any_setting_change()
        else:
            # 关掉取色窗口没确认 -> 调回之前的选项
            try:
                self.bg_var.set(back)
                self.bg_dd.set(back)
            except Exception:
                pass
            self._on_any_setting_change()

    def _on_pick_accent_color(self, value):
        """强调色：选预设直接生效；选「自定义…」打开取色器（取消则回到之前选的）"""
        if value != "自定义…":
            self._last_accent_sel = value
            self._on_any_setting_change()
            return
        back = getattr(self, "_last_accent_sel", "经典蓝")
        c = colorchooser.askcolor(title="选择强调色", color=ACCENT)[1]
        if c:
            self._custom_accent_hex = c
            self._on_any_setting_change()
        else:
            try:
                self.accent_var.set(back)
                self.accent_dd.set(back)
            except Exception:
                pass
            self._on_any_setting_change()

    def _toggle_obs_source(self):
        """开启/关闭 OBS 浏览器源（本地服务已在启动时开启，这里主要是反馈）"""
        on = bool(self.obs_var.get())
        self.settings["obs_browser_source"] = on
        # 地址一直有效（服务始终在跑），开关主要作为记忆/显示
        self._set_status("OBS 浏览器源已" + ("开启" if on else "关闭"), GOOD if on else DIM)

    def _copy_obs_addr(self):
        """复制 OBS 浏览器源地址到剪贴板"""
        try:
            from tkinter import Tk
            port = int(self.settings.get("api_port", 8765))
            url = f"http://127.0.0.1:{port}/overlay"
            r = self.clipboard_clear()
            self.clipboard_append(url)
            messagebox.showinfo("已复制", f"OBS 浏览器源地址已复制：\n{url}")
        except Exception:
            messagebox.showerror("失败", "复制失败，请手动复制地址。")

    def _choose_bg_image(self):
        """选择自定义背景图片（立即预览）"""
        p = filedialog.askopenfilename(
            title="选择背景图片",
            filetypes=[("图片文件", "*.png;*.jpg;*.jpeg;*.bmp;*.webp")],
        )
        if not p:
            return
        try:
            from PIL import Image
            Image.open(p).verify()
        except Exception:
            messagebox.showerror("失败", "这个文件不是有效的图片，请重新选择。")
            return
        self.settings["bg_image"] = p
        try:
            self._bg_img_label.configure(text=f"当前：{Path(p).name}")
        except Exception:
            pass
        self._apply_background()  # 立即预览
        # 立即保存（现在没有「保存设置」按钮了）
        try:
            config_manager.save_settings(self.settings)
        except Exception:
            pass

    def _clear_bg_image(self):
        """清除背景图片，恢复纯色"""
        self.settings["bg_image"] = ""
        try:
            self._bg_img_label.configure(text="未设置（纯色背景）")
        except Exception:
            pass
        self._apply_background()
        try:
            config_manager.save_settings(self.settings)
        except Exception:
            pass

    def _collect_settings(self):
        """把设置界面上的控件值读进 self.settings（不保存、不应用）"""
        try:
            val = int(self.tick_entry.get().strip())
            self.settings["tick_interval"] = max(10, min(5000, val))
        except Exception:
            pass
        change_map = {"高": 2.0, "中": 4.0, "低": 8.0}
        if hasattr(self, "change_var"):
            self.settings["change_threshold"] = change_map.get(self.change_var.get(), 4.0)
        try:
            self.settings["event_end_window"] = float(
                str(self.event_var.get()).replace("秒", "").strip())
        except Exception:
            pass
        ocr_map = {"快": 150, "标准": 250, "慢": 500}
        if hasattr(self, "ocr_var"):
            self.settings["ocr_interval"] = ocr_map.get(self.ocr_var.get(), 250)
        if hasattr(self, "auto_reg_var"):
            self.settings["auto_register_material"] = bool(self.auto_reg_var.get())
        if hasattr(self, "enable_mora_var"):
            self.settings["enable_mora"] = bool(self.enable_mora_var.get())
        if hasattr(self, "enable_mat_var"):
            self.settings["enable_material"] = bool(self.enable_mat_var.get())
        if hasattr(self, "enable_art_var"):
            self.settings["enable_artifact"] = bool(self.enable_art_var.get())
        if hasattr(self, "only_foreground_var"):
            self.settings["only_foreground"] = bool(self.only_foreground_var.get())
        if hasattr(self, "dataset_enabled_var"):
            self.settings["dataset_enabled"] = bool(self.dataset_enabled_var.get())
        if hasattr(self, "close_btn_var"):
            self.settings["close_behavior"] = {
                "每次询问": "ask", "最小化到托盘": "tray", "直接退出": "exit",
            }.get(self.close_btn_var.get(), "ask")
        # 外观
        if hasattr(self, "bg_var"):
            _bs = self.bg_var.get()
            self.settings["bg_color"] = (getattr(self, "_custom_bg_hex", None) or BG) if _bs == "自定义…" else _bs
        if hasattr(self, "accent_var"):
            _as = self.accent_var.get()
            self.settings["accent_color"] = (getattr(self, "_custom_accent_hex", None) or ACCENT) if _as == "自定义…" else _as
        if hasattr(self, "glass_var"):
            self.settings["sidebar_glass"] = bool(self.glass_var.get())
        if hasattr(self, "obs_var"):
            self.settings["obs_browser_source"] = bool(self.obs_var.get())
        # 换日时间
        _ro_changed = False
        try:
            if hasattr(self, "rollover_var"):
                _new_ro = int(self.rollover_var.get()) % 24
                _ro_changed = int(self.settings.get("rollover_hour", 0) or 0) != _new_ro
                self.settings["rollover_hour"] = _new_ro
        except Exception:
            pass
        # 统计条显示哪几个格子
        _bar = dict(self.settings.get("stat_bar") or {})
        _slots_changed = False
        for _key, _var in getattr(self, "_slot_vars", {}).items():
            _newv = bool(_var.get())
            if bool(_bar.get("show_" + _key, True)) != _newv:
                _slots_changed = True
            _bar["show_" + _key] = _newv
        self.settings["stat_bar"] = _bar
        return _ro_changed, _slots_changed

    def _apply_live_settings(self):
        """把设置同步到正在运行的检测器（立即生效）"""
        try:
            if self.detector:
                self.detector.settings = self.settings
                self.detector.change_threshold = float(self.settings.get("change_threshold", 4.0))
                self.detector.tracker.end_window = float(self.settings.get("event_end_window", 1.5))
                self.detector.ocr_interval = float(self.settings.get("ocr_interval", 250)) / 1000.0
        except Exception:
            pass

    def _on_any_setting_change(self, *_a):
        """任何设置一改：立刻写进 settings、立刻保存、立刻生效（不需要点保存按钮）"""
        try:
            _ro_changed, _slots_changed = self._collect_settings()
            config_manager.save_settings(self.settings)
            self._apply_live_settings()
            try:
                self._apply_hotkey()
            except Exception:
                pass
            if _ro_changed:
                try:
                    self.stats.rollover_hour = int(self.settings.get("rollover_hour", 0) or 0)
                    if self.stats.check_day():
                        self._prev_list_sig = None
                        self._refresh_ui()
                        self._rebuild_records()
                except Exception:
                    pass
            if _slots_changed:
                self._rebuild_stat_bar()
            # 背景图 / 面板透明度 / 侧边栏模糊 变了就重贴玻璃
            _bg_sig = (str(self.settings.get("bg_image") or ""),
                       round(self._glass_alpha(), 3),
                       bool(self.settings.get("sidebar_glass", True)),
                       round(float(self.settings.get("bg_dim", 0.0) or 0.0), 3))
            if getattr(self, "_bg_sig", None) != _bg_sig:
                self._apply_background()
        except Exception:
            pass

    def _rebuild_stat_bar(self):
        """统计条开着时，重开一次让「显示哪几个格子」立即生效"""
        try:
            if self.stat_bar is not None and self.stat_bar.winfo_exists():
                self.on_stat_bar_toggle()
                self.on_stat_bar_toggle()
        except Exception:
            pass

    def _on_tick_change(self, _e=None):
        """检测间隔输入框：边打字边保存（防抖 0.5 秒）"""
        try:
            if getattr(self, "_tick_after", None):
                try:
                    self.after_cancel(self._tick_after)
                except Exception:
                    pass
            self._tick_after = self.after(500, self._on_any_setting_change)
        except Exception:
            pass
