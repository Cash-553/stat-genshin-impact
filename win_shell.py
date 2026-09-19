# -*- coding: utf-8 -*-
"""窗口底层：无边框窗口的拖动/缩放、任务栏与圆角、全局热键、托盘与关闭行为。

这一块全是 Windows 相关的边角料，之所以麻烦是因为：
- Tk 的无边框窗口其实有两个 HWND，任务栏/缩略图只认真正的顶层窗口；
- 最小化必须用系统原生最小化，用 withdraw() 藏起来任务栏就叫不回来；
- 全局热键要子类化窗口过程，但只能处理 WM_HOTKEY，其它消息必须原样转发。"""
import sys
import time
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

import config_manager
from ui_base import (
    CARD, ACCENT, ACCENT_DARK, TEXT, DIM, BTN, BTN_HOVER, DANGER, DANGER_HOVER,
    FONT, HOTKEY_ID, WM_HOTKEY, _parse_hotkey,
)


class WindowShellMixin:
    def _bring_to_front(self):
        """启动后把窗口显示到所有窗口最前面（否则可能被别的窗口挡住）"""
        try:
            self.deiconify()
            self.lift()
            self.attributes("-topmost", True)
            self.update_idletasks()
            self.focus_force()
            # 短暂置顶后再取消，避免一直压着别的窗口
            self.after(500, lambda: self._set_not_topmost())
        except Exception:
            pass

    def _set_not_topmost(self):
        try:
            self.attributes("-topmost", False)
        except Exception:
            pass

    def _install_hotkey_proc(self):
        """子类化窗口过程，只处理 WM_HOTKEY。

        注意：这里【不拦截】任何其它消息，全部原样转发给 Tk，
        所以不会影响任务栏最小化/还原等系统行为。
        """
        if getattr(self, "_hk_proc_done", False):
            return
        try:
            import ctypes
            u = ctypes.windll.user32
            u.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
            u.SetWindowLongPtrW.restype = ctypes.c_void_p
            u.CallWindowProcW.argtypes = [
                ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_longlong,
            ]
            u.CallWindowProcW.restype = ctypes.c_longlong
            hwnd = int(self.winfo_id())
            if not hwnd:
                return
            WNDPROC = ctypes.WINFUNCTYPE(
                ctypes.c_longlong, ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_longlong,
            )

            def _proc(h, msg, wparam, lparam):
                # ctypes 回调里绝对不能抛异常（会 fail-fast 闪退）
                try:
                    if msg == WM_HOTKEY:
                        try:
                            self.after(0, self._on_hotkey)
                        except Exception:
                            pass
                        return 0
                except Exception:
                    pass
                try:
                    return u.CallWindowProcW(self._hk_orig, h, msg, wparam, lparam)
                except Exception:
                    return 0

            cb = WNDPROC(_proc)
            self._hk_cb = cb          # 保持引用，防回收
            old = u.SetWindowLongPtrW(hwnd, -4, ctypes.cast(cb, ctypes.c_void_p))
            if not old:
                return
            self._hk_orig = old
            self._hk_proc_done = True
        except Exception:
            pass

    def _uninstall_hotkey_proc(self):
        try:
            if getattr(self, "_hk_orig", 0):
                import ctypes
                u = ctypes.windll.user32
                u.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
                u.SetWindowLongPtrW.restype = ctypes.c_void_p
                u.SetWindowLongPtrW(int(self.winfo_id()), -4, self._hk_orig)
                self._hk_orig = 0
                self._hk_proc_done = False
        except Exception:
            pass

    def _apply_hotkey(self):
        """按设置注册/注销全局热键"""
        try:
            import ctypes
            u = ctypes.windll.user32
            hwnd = int(self.winfo_id())
            if not hwnd:
                return
            if getattr(self, "_hotkey_vk", None):
                try:
                    u.UnregisterHotKey(ctypes.c_void_p(hwnd), HOTKEY_ID)
                except Exception:
                    pass
                self._hotkey_vk = None
            spec = _parse_hotkey(self.settings.get("hotkey", "关闭"))
            if not spec:
                return
            mods, vk = spec
            ok = u.RegisterHotKey(ctypes.c_void_p(hwnd), HOTKEY_ID, mods | 0x4000, vk)
            if ok:
                self._hotkey_vk = vk
        except Exception:
            pass

    def _on_hotkey(self):
        """按下全局热键：开始 / 停止监测"""
        try:
            self.on_start_stop()
        except Exception:
            pass

    def _setup_window_extras(self):
        """窗口显示后要做的几件事（任务栏样式 + 热键 + 圆角）"""
        self._enable_taskbar()
        self._round_window_corners()
        self._install_hotkey_proc()
        self._apply_hotkey()

    def _hwnd_top(self):
        """返回【真正的顶层窗口】句柄。

        重要：Tk 的无边框窗口其实有两个 HWND——
        - self.winfo_id() 拿到的是“客户区子窗口”
        - 真正的顶层窗口是它的根祖先（GetAncestor GA_ROOT）
        任务栏按钮、缩略图预览、Alt+Tab、任务视图 只认顶层窗口，
        作用在子窗口上统统无效（这就是“缩略图黑屏 / 任务视图找不到”的根源）。
        """
        try:
            import ctypes
            u = ctypes.windll.user32
            u.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            u.GetAncestor.restype = ctypes.c_void_p
            child = int(self.winfo_id())
            if not child:
                return 0
            top = u.GetAncestor(ctypes.c_void_p(child), 2)  # GA_ROOT = 2
            return int(top) if top else child
        except Exception:
            return 0

    def _round_window_corners(self):
        """把窗口四个角改成圆角（用 Windows 11 自带的 DWM 圆角）

        无边框窗口用这个是有效的（实测过），而且是系统画的、带抗锯齿，
        比自己裁一块圆角区域（边缘会有锯齿）好看。
        Win10 上不支持，会直接忽略、保持直角，不会报错。
        """
        try:
            import ctypes
            from ctypes import wintypes
            hwnd = self._hwnd_top()
            if not hwnd:
                return
            DWMWA_WINDOW_CORNER_PREFERENCE = 33
            DWMWCP_ROUND = 2
            pref = ctypes.c_int(DWMWCP_ROUND)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(hwnd), DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(pref), ctypes.sizeof(pref))
        except Exception:
            pass

    def _enable_taskbar(self):
        """让无边框窗口像普通程序一样出现在 任务栏 / Alt+Tab / 任务视图，
        并且支持任务栏缩略图预览。

        Tk 的 overrideredirect（无边框）顶层窗口默认带 WS_EX_TOOLWINDOW，
        而 Windows 对“工具窗口”的处理是：任务栏、Alt+Tab、任务视图里全都
        不显示它（所以之前任务视图里找不到、缩略图也是黑屏）。
        修法：在【真正的顶层窗口】上去掉 TOOLWINDOW、加上 APPWINDOW。

        需要在窗口真正显示（Map）后再调用才有效，所以：
        - 启动后延时调用
        - 绑定 <Map> 事件：窗口每次显示（含从托盘恢复）都重新确保

        注意：<Map> 事件会被频繁触发（启动时控件逐个映射，可能上百次），
        而这个函数每次都要创建 COM 对象（很贵）。所以这里做去重：
        0.6 秒内重复触发直接跳过，避免白白卡启动。

        另外还要给窗口补上 WS_MINIMIZEBOX | WS_SYSMENU：
        无边框窗口是 WS_POPUP，默认没有这两位，系统就不知道它能最小化，
        表现为「点任务栏图标没反应」。补上后任务栏点击可正常最小化/还原。
        """
        _now = time.time()
        if _now - getattr(self, "_taskbar_last", 0.0) < 0.6:
            return
        self._taskbar_last = _now
        try:
            import ctypes
            hwnd = self._hwnd_top()
            if hwnd == 0:
                return  # 窗口句柄还没创建好，等下次再试
            u = ctypes.windll.user32
            u.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
            u.GetWindowLongW.restype = ctypes.c_long
            u.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
            u.SetWindowLongW.restype = ctypes.c_long
            GWL_EXSTYLE = -20
            GWL_STYLE = -16
            WS_EX_TOOLWINDOW = 0x00000080
            WS_EX_APPWINDOW = 0x00040000
            # 无边框窗口是 WS_POPUP，默认没有「可最小化/系统菜单」样式，
            # 结果点任务栏图标时系统不知道该最小化它（点了没反应）。
            # 补上这两位后，任务栏点击就能正常 最小化 / 还原。
            WS_MINIMIZEBOX = 0x00020000
            WS_SYSMENU = 0x00080000
            _st = u.GetWindowLongW(ctypes.c_void_p(hwnd), GWL_STYLE)
            _new_st = _st | WS_MINIMIZEBOX | WS_SYSMENU
            if _new_st != _st:
                u.SetWindowLongW(ctypes.c_void_p(hwnd), GWL_STYLE, _new_st)
            style = u.GetWindowLongW(ctypes.c_void_p(hwnd), GWL_EXSTYLE)
            new_style = (style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
            if new_style != style:
                u.SetWindowLongW(ctypes.c_void_p(hwnd), GWL_EXSTYLE, new_style)
            SWP_FRAMECHANGED = 0x0020
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOZORDER = 0x0004
            u.SetWindowPos(ctypes.c_void_p(hwnd), 0, 0, 0, 0, 0,
                           SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER)
            # 改了窗口样式之后，Win11 的圆角可能会被重置，这里补设一次
            self._round_window_corners()
        except Exception:
            pass
        # ITaskbarList::AddTab 强制加入任务栏
        try:
            import ctypes
            from ctypes import POINTER, Structure, byref, c_void_p, c_ulong, c_ushort, c_ubyte

            class GUID(Structure):
                _fields_ = [
                    ("Data1", c_ulong), ("Data2", c_ushort), ("Data3", c_ushort), ("Data4", c_ubyte * 8),
                ]

            def make_guid(s):
                s = s.replace("{", "").replace("}", "").replace("-", "")
                g = GUID()
                g.Data1 = int(s[0:8], 16)
                g.Data2 = int(s[8:12], 16)
                g.Data3 = int(s[12:16], 16)
                for i in range(8):
                    g.Data4[i] = int(s[16 + i * 2:18 + i * 2], 16)
                return g

            ole32 = ctypes.oledll.ole32
            ole32.CoInitialize(None)
            clsid = make_guid("56FDF344-FD6D-11d0-958A-006097C9A090")
            iid = make_guid("56FDF342-FD6D-11d0-958A-006097C9A090")
            p = c_void_p()
            hr = ole32.CoCreateInstance(byref(clsid), None, 1, byref(iid), byref(p))
            if hr == 0 and p:
                pp = ctypes.cast(p, POINTER(c_void_p))
                vtable = ctypes.cast(pp[0], POINTER(c_void_p))
                # ITaskbarList: [3]=HrInit, [4]=AddTab（必须先 HrInit 再 AddTab！）
                HrInit = ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p)(vtable[3])
                HrInit(p)
                AddTab = ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, c_void_p)(vtable[4])
                AddTab(p, c_void_p(self._hwnd_top()))
                Release = ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p)(vtable[2])
                Release(p)
            ole32.CoUninitialize()
        except Exception:
            pass

    def _icon_path(self):
        """找到程序图标文件 app_icon.ico：
        - 打包版：从内置资源里找（_MEIPASS）
        - 开发版：项目目录
        """
        if getattr(sys, "frozen", False):
            base = getattr(sys, "_MEIPASS", str(Path(sys.executable).parent))
            p = Path(base) / "app_icon.ico"
            if p.exists():
                return p
        p = Path(__file__).resolve().parent / "app_icon.ico"
        return p if p.exists() else None

    def _set_window_icon(self):
        """设置窗口图标（任务栏按钮 / Alt+Tab 都显示程序图标，而不是 Tk 默认图标）"""
        try:
            ico = self._icon_path()
            if ico is None:
                return
            try:
                # 最简单可靠：iconbitmap 直接吃 .ico（Windows 原生）
                self.iconbitmap(default=str(ico))
            except Exception:
                # 兜底：PIL 转 PNG 再用 iconphoto（兼容性更好）
                from PIL import Image
                import io
                import tkinter as tk
                img = Image.open(ico).convert("RGBA")
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                buf.seek(0)
                photo = tk.PhotoImage(data=buf.read())
                self._icon_photo = photo  # 防止被回收
                self.iconphoto(True, photo)
        except Exception:
            pass

    def _resize_start(self, event):
        self._rz_x = event.x_root
        self._rz_y = event.y_root
        self._rz_w = self.winfo_width()
        self._rz_h = self.winfo_height()

    def _resize_right(self, event):
        nw = max(700, self._rz_w + (event.x_root - self._rz_x))
        self.geometry(f"{nw}x{self.winfo_height()}")

    def _resize_bottom(self, event):
        nh = max(520, self._rz_h + (event.y_root - self._rz_y))
        self.geometry(f"{self.winfo_width()}x{nh}")

    def _resize_corner(self, event):
        nw = max(700, self._rz_w + (event.x_root - self._rz_x))
        nh = max(520, self._rz_h + (event.y_root - self._rz_y))
        self.geometry(f"{nw}x{nh}")

    def _drag_start(self, event):
        self._drag_x = event.x_root - self.winfo_x()
        self._drag_y = event.y_root - self.winfo_y()

    def _drag_move(self, event):
        try:
            self.geometry(f"+{event.x_root - self._drag_x}+{event.y_root - self._drag_y}")
        except Exception:
            pass

    def _minimize_to_tray(self):
        """最小化窗口（用系统原生最小化，而不是 withdraw() 隐藏）。

        为什么不用 withdraw()：
        withdraw() 会把窗口彻底隐藏（窗口消失），于是任务栏缩略图没有内容
        可显示 → 预览黑屏；任务视图里也看不到这个窗口。
        改用系统原生最小化（SW_MINIMIZE）后窗口仍然“活着”，
        Windows 才能正常生成缩略图预览，任务视图里也能找到。
        监测线程不受影响，照常继续。
        """
        try:
            self._min_saved_pos = (self.winfo_x(), self.winfo_y())
        except Exception:
            self._min_saved_pos = None
        self._minimized = True
        ok = False
        try:
            import ctypes
            hwnd = self._hwnd_top()
            if hwnd:
                u = ctypes.windll.user32
                u.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
                u.ShowWindow.restype = ctypes.c_int
                u.ShowWindow(ctypes.c_void_p(hwnd), 6)  # SW_MINIMIZE
                ok = True
        except Exception:
            ok = False
        if not ok:
            # 兜底：万一原生最小化失败，仍用隐藏（保证不会卡住界面）
            try:
                self.withdraw()
            except Exception:
                pass

    def show_main(self):
        """呼出主窗口（从任务栏按钮 / 托盘图标）"""
        self._minimized = False
        try:
            # 恢复最小化前的位置
            if getattr(self, "_min_saved_pos", None):
                try:
                    self.geometry(f"+{self._min_saved_pos[0]}+{self._min_saved_pos[1]}")
                except Exception:
                    pass
            # 窗口是被原生最小化的，Tk 的 deiconify 对无边框窗口无效，
            # 必须用系统的 SW_RESTORE 还原
            try:
                import ctypes
                hwnd = self._hwnd_top()
                if hwnd:
                    u = ctypes.windll.user32
                    u.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
                    u.ShowWindow.restype = ctypes.c_int
                    u.ShowWindow(ctypes.c_void_p(hwnd), 9)  # SW_RESTORE
            except Exception:
                pass
            self.deiconify()
            self.lift()
            self.focus_force()
            # 从托盘恢复后确保任务栏按钮还在
            self.after(150, self._enable_taskbar)
        except Exception:
            pass

    def on_close(self):
        """点窗口 ✕：按设置处理（每次询问 / 最小化到托盘 / 直接退出）"""
        behavior = self.settings.get("close_behavior", "ask")
        if behavior == "exit":
            self.on_exit()
        elif behavior == "tray":
            self._minimize_to_tray()
            if not getattr(self, "_tray_hint", False):
                self._tray_hint = True
                messagebox.showinfo("提示", "程序已最小化，监测仍在继续。\n点击任务栏图标或托盘图标可恢复窗口。")
        else:
            self._ask_close()

    def _ask_close(self):
        """弹窗询问：关闭程序 / 最小化到托盘 / 取消（在主窗口中间弹出）"""
        dlg = ctk.CTkToplevel(self)
        dlg.title("退出确认")
        dlg.geometry("380x210")
        dlg.resizable(False, False)
        try:
            dlg.transient(self)
            dlg.grab_set()  # 模态：必须先选择
        except Exception:
            pass
        dlg.configure(fg_color=CARD)
        # 居中显示在主窗口中间
        try:
            dlg.update_idletasks()
            self.update_idletasks()
            mw, mh = self.winfo_width(), self.winfo_height()
            mx, my = self.winfo_rootx(), self.winfo_rooty()
            dw, dh = 380, 210
            dlg.geometry(f"+{mx + (mw - dw) // 2}+{my + (mh - dh) // 2}")
        except Exception:
            pass

        ctk.CTkLabel(
            dlg, text="要关闭程序，还是最小化到托盘？",
            font=(FONT, 17, "bold"), text_color=TEXT,
        ).pack(pady=(22, 4))
        ctk.CTkLabel(
            dlg, text="最小化后监测会继续运行",
            font=(FONT, 13), text_color=DIM,
        ).pack(pady=(0, 12))

        def _do_exit():
            try:
                dlg.destroy()
            except Exception:
                pass
            self.on_exit()

        def _do_tray():
            try:
                dlg.destroy()
            except Exception:
                pass
            self._minimize_to_tray()

        def _do_cancel():
            try:
                dlg.destroy()
            except Exception:
                pass

        row = ctk.CTkFrame(dlg, fg_color="transparent")
        row.pack(pady=(4, 18))
        ctk.CTkButton(
            row, text="🗑 关闭程序", font=(FONT, 16), width=100, height=36,
            fg_color=DANGER, hover_color=DANGER_HOVER, text_color=TEXT, command=_do_exit,
        ).pack(side="left", padx=6)
        ctk.CTkButton(
            row, text="📌 最小化到托盘", font=(FONT, 16), width=130, height=36,
            fg_color=ACCENT, hover_color=ACCENT_DARK, text_color="#FFFFFF", command=_do_tray,
        ).pack(side="left", padx=6)
        ctk.CTkButton(
            row, text="取消", font=(FONT, 16), width=80, height=36,
            fg_color=BTN, hover_color=BTN_HOVER, text_color=TEXT, command=_do_cancel,
        ).pack(side="left", padx=6)

        dlg.protocol("WM_DELETE_WINDOW", _do_cancel)
        try:
            dlg.after(100, dlg.lift)
        except Exception:
            pass
        try:
            self.wait_window(dlg)
        except Exception:
            pass

    def on_exit(self):
        # 先恢复原窗口过程（防止销毁过程中回调悬空导致闪退）
        try:
            self._uninstall_hotkey_proc()
        except Exception:
            pass
        try:
            if self.stat_bar is not None:
                self.stat_bar.close_bar()
        except Exception:
            pass
        try:
            self.stop_monitor()
        except Exception:
            pass
        try:
            self.tray.stop()
        except Exception:
            pass
        # detector 由后台检测线程负责关闭（这里不再碰，避免跨线程冲突）
        self.detector = None
        self.destroy()
