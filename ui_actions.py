# -*- coding: utf-8 -*-
"""各种「按一下做件事」的操作：清空、材料明细、收益记录、检查更新、
诊断截图、收益统计条、图标、直播数据接口。

这些方法之间没什么耦合，基本都是一个按钮对应一个。
"""
import time
import threading
import webbrowser
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

import theme
import sessions
from icon_manager import IconManagerWindow
from ui_base import (
    BASE_DIR, CARD_INNER, ACCENT, TEXT, DIM, GOOD, BAD, FONT,
)


class ActionsMixin:
    def _on_clear_selected(self):
        """按浮动下拉的选择执行清空"""
        try:
            choice = self.clear_dd.get()
        except Exception:
            choice = "清空今日数据"
        if choice == "清空监测时间":
            self.on_clear_runtime()
        elif choice == "清空数据和时间":
            self.on_clear_all()
        else:
            self.on_clear_today()

    def on_clear_all(self):
        """清空今日数据 + 监测时间（收益记录不动）"""
        if not messagebox.askyesno("确认", "确定清空今天的收益数据和监测时间吗？\n（收益记录不受影响）"):
            return
        self.stats.clear_today()
        self.stats.clear_running_seconds()
        if self.monitoring:
            self._monitor_start = time.monotonic()
        self._refresh_ui()
        messagebox.showinfo("已清空", "今日数据和监测时间已清空")

    def _toggle_material_detail(self):
        """在「今日统计」的材料卡片里，就地切换「简要列表 / 完整明细」"""
        self._detail_shown = not getattr(self, "_detail_shown", False)
        try:
            if self._detail_shown:
                self.mat_scroll.pack_forget()
                self.detail_frame.pack(fill="both", expand=True, padx=10, pady=(2, 10))
                self.detail_toggle_btn.configure(text="收起明细")
                self._rebuild_detail_list()
            else:
                self.detail_frame.pack_forget()
                self.mat_scroll.pack(fill="both", expand=True, padx=10, pady=(2, 10))
                self.detail_toggle_btn.configure(text="查看明细")
        except Exception:
            pass
        # 明细区刚显示出来，补贴一次玻璃
        self._glass_schedule_refresh()

    @staticmethod
    def _fmt_dur(sec):
        sec = int(max(0, sec))
        h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
        if h:
            return f"{h}小时{m}分"
        if m:
            return f"{m}分{s}秒"
        return f"{s}秒"

    def _rebuild_records(self):
        sc = getattr(self, "records_scroll", None)
        if sc is None:
            return
        for w in sc.winfo_children():
            w.destroy()
        self._rec_widgets = {}
        items = sessions.load_sessions()
        if not items:
            ctk.CTkLabel(
                sc, text="（还没有记录）\n点「开始监测」跑一段时间，再点「停止监测」，就会生成一条。",
                font=(FONT, 15), text_color=DIM, justify="left",
            ).pack(pady=24)
            self._glass_schedule_refresh()
            return
        # 最新的排在最上面
        for idx in range(len(items) - 1, -1, -1):
            self._make_record_card(sc, idx, items[idx])
        # 上面这些都是刚造出来的控件，补贴一次玻璃
        self._glass_schedule_refresh()

    def _toggle_record_detail(self, idx):
        w = getattr(self, "_rec_widgets", {}).get(idx)
        if not w:
            return
        detail, btn = w
        if not hasattr(self, "_rec_open"):
            self._rec_open = set()
        if idx in self._rec_open:
            self._rec_open.discard(idx)
            detail.pack_forget()
            btn.configure(text="查看明细 ▾")
        else:
            self._rec_open.add(idx)
            detail.pack(fill="x", padx=12, pady=(0, 8))
            btn.configure(text="收起明细 ▴")
        # 明细区刚显示出来，里面那些控件之前不可见、还没贴过玻璃，补贴一次
        self._glass_schedule_refresh()

    def on_clear_records(self):
        if not messagebox.askyesno("确认", "确定清空所有收益记录吗？\n（今日统计的数据不受影响）"):
            return
        sessions.clear_sessions()
        self._rec_open = set()
        self._rebuild_records()
        messagebox.showinfo("已清空", "收益记录已清空")

    def on_icon_manager(self):
        """打开图标管理窗口（收益统计条三个格子的图标）。

        只能开一个：已经开着就把它拎到前面来，不再开第二个。
        """
        win = getattr(self, "_icon_win", None)
        if win is not None:
            try:
                if win.winfo_exists():
                    win.lift()
                    win.focus_force()
                    return
            except Exception:
                pass
            self._icon_win = None
        try:
            self._icon_win = IconManagerWindow(
                self, on_change=self.reload_icons,
                on_closed=lambda: setattr(self, "_icon_win", None))
            self._icon_win.show()
        except Exception:
            self._icon_win = None
            messagebox.showerror("打开失败", "图标管理窗口打不开，请重启程序再试。")

    def on_check_update(self):
        """检测 GitHub Releases 是否有新版本（后台线程，不卡界面）"""
        self.update_status_label.configure(text="正在检测…", text_color=DIM)
        import threading

        def _do():
            try:
                import urllib.request
                import json
                req = urllib.request.Request(
                    "https://api.github.com/repos/Cash-553/stat-genshin-impact/releases/latest",
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                latest = str(data.get("tag_name", "")).lstrip("v")
                current = "0.7"
                if latest and latest != current:
                    url = data.get("html_url", "https://github.com/Cash-553/stat-genshin-impact/releases")
                    self.after(0, lambda: self._update_found(latest, current, url))
                elif latest:
                    self.after(0, lambda: self.update_status_label.configure(text="已是最新版本", text_color=theme.GOOD))
                else:
                    self.after(0, lambda: self.update_status_label.configure(text="未获取到版本信息", text_color=DIM))
            except Exception:
                self.after(0, lambda: self.update_status_label.configure(text="检测失败（需联网）", text_color=BAD))

        threading.Thread(target=_do, daemon=True).start()

    def _update_found(self, latest, current, url):
        try:
            self.update_status_label.configure(text=f"发现新版本 {latest}", text_color=ACCENT)
            if messagebox.askyesno("发现新版本", f"当前版本 {current}\n最新版本 {latest}\n\n是否打开下载页面？"):
                import webbrowser
                webbrowser.open(url)
        except Exception:
            pass

    def reload_icons(self):
        """图标变动后重新加载（刷新统计条图标）"""
        self.materials = materials_db.load_materials()
        if self.stat_bar is not None:
            try:
                if self.stat_bar.winfo_exists():
                    self.stat_bar._refresh()  # 立即刷新统计条图标
            except Exception:
                pass

    def on_clear_today(self):
        if not messagebox.askyesno("确认", "确定清空今天的所有收益吗？\n（历史数据不受影响）"):
            return
        self.stats.clear_today()
        self._refresh_ui()
        messagebox.showinfo("已清空", "今天的收益已清空")

    def on_clear_runtime(self):
        """单独清空监测时间（收益数据不动）。正在监测时从中断点重新计时。"""
        if not messagebox.askyesno("确认", "确定清空监测时间吗？\n（摩拉、材料等收益不受影响）"):
            return
        self.stats.clear_running_seconds()
        # 若正在监测，重置本次开始时间，让监测时间从 0 重新累计
        if self.monitoring:
            self._monitor_start = time.monotonic()
        self._refresh_ui()
        messagebox.showinfo("已清空", "监测时间已清空")

    def on_debug_screenshot(self):
        """保存当前识别区域的截图，并 OCR 显示画面里有什么（用于确认框选是否正确）"""
        region = self.settings.get("region")
        if not region:
            messagebox.showinfo("提示", "请先框选识别区域")
            return
        try:
            from capture import ScreenCapture
            c = ScreenCapture()
            try:
                frame = c.grab(region)
            finally:
                c.close()
            from PIL import Image
            img = Image.fromarray(frame[:, :, :3][:, :, ::-1])
            d = Path(BASE_DIR) / "data" / "debug"
            d.mkdir(parents=True, exist_ok=True)
            f = d / f"manual_{time.strftime('%Y%m%d_%H%M%S')}.png"
            img.save(f)

            # OCR 看看画面里有什么（帮助确认框选区域是否正确）
            from ocr_engine import OcrEngine
            ocr = OcrEngine()
            lines = ocr.recognize(frame)
            if lines:
                texts = "\n".join(f"· {t}" for t, s in lines[:6])
                messagebox.showinfo(
                    "截图已保存",
                    f"截图已保存：\n{f}\n\n画面里识别到的内容：\n{texts}\n\n"
                    "💡 检查：如果这里显示的是掉落提示（如「破损的面具 ×1」），说明框对了；\n"
                    "如果是其他文字，说明区域没框对，请重新框选。",
                )
            else:
                messagebox.showinfo(
                    "截图已保存",
                    f"截图已保存：\n{f}\n\n画面里没有识别到文字。\n"
                    "💡 如果掉落提示出现时这里仍是空白，说明区域没框对，请重新框选。",
                )
        except Exception as e:
            messagebox.showerror("失败", f"截图失败：{e}")

    def on_stat_bar_toggle(self):
        """打开/关闭横向统计条"""
        if self.stat_bar is not None:
            try:
                if self.stat_bar.winfo_exists():
                    self.stat_bar.close_bar()
            except Exception:
                pass
            self.stat_bar = None
            self.bar_btn.configure(text="📶 打开统计条")
            return
        from overlay_bar import StatBar
        self.stat_bar = StatBar(
            self,
            stats_provider=self._stat_bar_data,
            settings_provider=lambda: self.settings.get("stat_bar", {}),
            on_closed=lambda: self._on_bar_closed(),
        )
        self.bar_btn.configure(text="📶 隐藏统计条")

    def _on_bar_closed(self):
        self.stat_bar = None
        try:
            self.bar_btn.configure(text="📶 打开统计条")
        except Exception:
            pass

    def _stat_bar_data(self):
        return {
            "mora": self.stats.mora,
            "material_total": sum(self.stats.materials.values()) + sum(self.stats.normal_materials.values()),
            "artifact": self.stats.artifact,
        }

    def _rebuild_mat_list(self, items=None):
        """首页的材料列表（合并怪物+普通）"""
        for w in self.mat_scroll.winfo_children():
            w.destroy()
        if items is None:
            items = dict(self.stats.materials)
            for k, v in self.stats.normal_materials.items():
                items[k] = items.get(k, 0) + v
        items = sorted(items.items(), key=lambda kv: -kv[1])
        if not items:
            ctk.CTkLabel(
                self.mat_scroll, text="（暂无，开始监测后自动统计）",
                font=(FONT, 15), text_color=DIM,
            ).pack(pady=16)
            self._glass_schedule_refresh()
            return
        for name, count in items:
            row = ctk.CTkFrame(self.mat_scroll, fg_color="transparent")
            row.pack(fill="x", padx=6, pady=2)
            ctk.CTkLabel(row, text=name, font=(FONT, 16), text_color=TEXT).pack(side="left")
            ctk.CTkLabel(row, text=f"×{count}", font=(FONT, 16, "bold"), text_color=ACCENT).pack(side="right")
        self._glass_schedule_refresh()

    def _rebuild_detail_list(self):
        """素材明细页：合并怪物+普通为一个列表"""
        for w in self.detail_scroll.winfo_children():
            w.destroy()
        merged = dict(self.stats.materials)
        for k, v in self.stats.normal_materials.items():
            merged[k] = merged.get(k, 0) + v
        items = sorted(merged.items(), key=lambda kv: -kv[1])
        if not items:
            ctk.CTkLabel(
                self.detail_scroll, text="（还没有识别到材料）",
                font=(FONT, 16), text_color=DIM,
            ).pack(pady=20)
        else:
            for i, (name, count) in enumerate(items, 1):
                row = ctk.CTkFrame(self.detail_scroll, fg_color=CARD_INNER, corner_radius=8)
                row.pack(fill="x", padx=8, pady=3)
                ctk.CTkLabel(row, text=f"{i:>2}", font=(FONT, 16), text_color=DIM, width=30).pack(side="left", padx=(10, 2), pady=8)
                ctk.CTkLabel(row, text=name, font=(FONT, 17), text_color=TEXT).pack(side="left", padx=6, pady=8)
                ctk.CTkLabel(row, text=f"×{count}", font=(FONT, 17, "bold"), text_color=ACCENT).pack(side="right", padx=14)
        total = sum(merged.values())
        self.detail_total_label.configure(
            text=f"共 {len(items)} 种材料，合计 {total} 个"
        )
        self._glass_schedule_refresh()

    def _api_data(self):
        total = self.stats.running_seconds
        if self.monitoring and self._monitor_start:
            total += int(time.monotonic() - self._monitor_start)
        return {
            "date": self.stats.date,
            "mora": self.stats.mora,
            "materials": dict(self.stats.materials),
            "material_total": sum(self.stats.materials.values()),
            "artifact": self.stats.artifact,
            "running_seconds": total,
            "monitoring": self.monitoring,
        }
