# -*- coding: utf-8 -*-
"""
StatGI —— 原神收益统计器 主程序

界面：无边框窗口，黑白灰 + 蓝色强调（深色主题），侧边栏导航 + 卡片式内容。

功能：
- 自动识别游戏窗口（不用手动框选），纯文字识别掉落提示
- 开始/停止监测：自动统计摩拉、怪物素材、圣遗物（狗粮）
- 防重复统计：同一个提示只统计一次
- 今日收益：自动换日、本地保存、一键清空
- 横向收益统计条（直播间小窗口，三个格子图标+数量）
- 系统托盘：最小化到托盘继续监测
- 图标管理：统计条格子图标自定义（图片识别已停用，以后可恢复）
- 直播数据接口：http://127.0.0.1:8765/api （给 OBS 用）
- 设置：检测间隔、灵敏度、防重复窗口、OCR频率、识别内容开关、运行行为等
"""
import sys
import time
import threading
import queue
from pathlib import Path

import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox, filedialog, colorchooser

import config_manager
import sessions
from ui_widgets import FloatingDropdown, Accordion
import materials_db
import paths
import region_selector
import theme
from detector import Detector
from stats import DailyStats
from icon_manager import IconManagerWindow
from tray import Tray
from api_server import ApiServer
from dataset_collector import DatasetCollector

BASE_DIR = paths.app_dir()
ICONS_DIR = paths.icons_dir()

# 界面主题（BetterGI 风格）
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

BG = theme.BG
SIDEBAR = theme.SIDEBAR
HEADER = theme.HEADER
CARD = theme.CARD
CARD_INNER = theme.CARD_INNER
ACCENT = theme.ACCENT
ACCENT_DARK = theme.ACCENT_DARK
TEXT = theme.TEXT
DIM = theme.DIM
# 开关「关闭」时的轨道颜色（灰色，这样一眼能看出开/关）
SWITCH_OFF = "#5A5A5A"
GOOD = theme.GOOD
BAD = theme.BAD
NAV_ON = theme.NAV_ON
BTN = theme.BTN
BTN_HOVER = theme.BTN_HOVER
DANGER = theme.DANGER
DANGER_HOVER = theme.DANGER_HOVER
RADIUS_CARD = theme.RADIUS_CARD
RADIUS_BTN = theme.RADIUS_BTN
RADIUS_INNER = theme.RADIUS_INNER

from fonts import FONT  # Win11 字体（Segoe UI Variable）


def fmt_time(seconds):
    """把秒数变成 时:分:秒"""
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


# ================= 全局热键 =================
# 设置里存的是 "Ctrl+Alt+S" / "F9" / "关闭" 这样的字符串，完全自定义
HOTKEY_ID = 0xA501
WM_HOTKEY = 0x0312


def _keysym_to_vk(ks):
    """Tk 的 keysym（F9 / S / SPACE…）-> Windows 虚拟键码"""
    ks = (ks or "").upper()
    if len(ks) == 1 and ks.isalnum():
        return ord(ks)
    if ks.startswith("F") and ks[1:].isdigit():
        n = int(ks[1:])
        if 1 <= n <= 24:
            return 0x70 + n - 1
    return {
        "SPACE": 0x20, "TAB": 0x09, "RETURN": 0x0D, "BACKSPACE": 0x08,
        "INSERT": 0x2D, "DELETE": 0x2E, "HOME": 0x24, "END": 0x23,
        "PRIOR": 0x21, "NEXT": 0x22, "UP": 0x26, "DOWN": 0x28,
        "LEFT": 0x25, "RIGHT": 0x27, "MINUS": 0xBD, "EQUAL": 0xBB,
        "BRACKETLEFT": 0xDB, "BRACKETRIGHT": 0xDD, "BACKSLASH": 0xDC,
        "SEMICOLON": 0xBA, "APOSTROPHE": 0xDE, "COMMA": 0xBC,
        "PERIOD": 0xBE, "SLASH": 0xBF, "GRAVE": 0xC0,
    }.get(ks)


def _hotkey_name(mods, key):
    """(修饰键, 键名) -> 保存用的字符串"""
    parts = []
    if mods & 0x0002:
        parts.append("Ctrl")
    if mods & 0x0001:
        parts.append("Alt")
    if mods & 0x0004:
        parts.append("Shift")
    if mods & 0x0008:
        parts.append("Win")
    parts.append(str(key).upper())
    return "+".join(parts)


def _parse_hotkey(s):
    """字符串 -> (mods, vk)；无法解析返回 None"""
    s = str(s or "").strip()
    if not s or s in ("关闭", "无", "None") or s.startswith("这个键"):
        return None
    mods = 0
    key = None
    for part in s.split("+"):
        p = part.strip().upper()
        if p in ("CTRL", "CONTROL"):
            mods |= 0x0002
        elif p == "ALT":
            mods |= 0x0001
        elif p == "SHIFT":
            mods |= 0x0004
        elif p in ("WIN", "SUPER"):
            mods |= 0x0008
        elif p:
            key = p
    if not key:
        return None
    vk = _keysym_to_vk(key)
    if vk is None:
        return None
    return mods, vk


class MainApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("StatGI")
        self.overrideredirect(True)   # 无边框窗口（插件风格）
        # 把 CustomTkinter 的缩放锁成整数 1.0。
        # 原因：110% / 125% 这类「非整数缩放」会让 canvas 的坐标出现小数，
        # 滚动时像素对不齐 —— 表现就是设置页上下滚动时文字留下很重的拖影。
        # 锁成 1.0 后所有控件按整像素渲染，拖影消失（文字会略小一点点）。
        try:
            from customtkinter.windows.widgets.scaling.scaling_tracker import ScalingTracker as _ST
            _d = _ST.get_window_dpi_scaling(self) or 1.0
            ctk.set_widget_scaling(1.0 / _d)
            ctk.set_window_scaling(1.0 / _d)
        except Exception:
            try:
                ctk.set_widget_scaling(1.0)
                ctk.set_window_scaling(1.0)
            except Exception:
                pass
        # 初始大小 900×660（卡片放大后需要更高的窗口），窗口居中
        self.geometry("900x660")
        self.resizable(False, False)  # 无边框窗口用自定义边缘拖拽调大小
        self.update_idletasks()
        try:
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            w, h = self.winfo_width(), self.winfo_height()
            x = max(0, (sw - w) // 2)
            y = max(0, (sh - h) // 2)
            self.geometry(f"+{int(x)}+{int(y)}")
        except Exception:
            pass
        # 无边框窗口也显示在任务栏（图标 + 按钮）
        self._set_window_icon()
        self._enable_taskbar()
        # 窗口每次显示（含从托盘恢复）都重新确保任务栏按钮；启动后再补几次，防时机问题
        self.bind("<Map>", lambda e: self.after(100, self._setup_window_extras))
        self.after(300, self._setup_window_extras)
        self.after(1200, self._enable_taskbar)
        self._drag_x = 0
        self._drag_y = 0
        self._rz_x = self._rz_y = self._rz_w = self._rz_h = 0
        self._minimized = False  # 是否处于"最小化（屏幕外）"状态
        # 检测线程（OCR 很慢，必须在后台线程跑，否则界面卡死）
        self._detect_thread = None
        self._detect_stop = None
        self._detect_queue = queue.Queue()
        self._detect_err_streak = 0

        self.settings = config_manager.load_settings()
        # 换日时间（0=自然日；4=凌晨4点换日，挂过零点不会突然归零）
        try:
            _ro = int(self.settings.get("rollover_hour", 0))
        except Exception:
            _ro = 0
        self.stats = DailyStats(rollover_hour=_ro)
        self.detector = None          # 开始监测时才创建
        self.monitoring = False
        self.stat_bar = None          # 横向统计条窗口
        self._monitor_start = None    # 本次监测开始的时间
        self._prev_list_sig = None    # 上次刷新的素材列表签名
        self._error_streak = 0        # 连续出错次数
        self._current_page = "home"   # 当前页面
        self._tick_interval = int(self.settings.get("tick_interval", 500))  # 检测间隔(毫秒)

        self._build_ui()
        self._show_page("launch")
        self._refresh_region_state()
        self._refresh_ui()

        # 系统托盘 + 直播接口
        self.tray = Tray()
        self.tray.start()
        self.api = ApiServer(port=int(self.settings.get("api_port", 8765)))
        self.api.set_provider(self._api_data)
        self.api.start()

        # 主循环（每 0.5 秒一次）
        self.after(300, self._tick_loop)

        # 自定义背景（图片铺底 + 毛玻璃侧边栏）；窗口尺寸变化时重新生成
        self._resize_after = None
        self.bind("<Configure>", self._on_resize)
        self.after(200, self._apply_background)

        # 启动后把窗口显示到最前面
        self.after(350, self._bring_to_front)

        # 启动后空闲时把其它页面依次预建好：
        # 首屏不受影响（启动快），等用户点过去时页面已经建好（切页不卡）
        self.after(250, lambda: self._prebuild_pages("home", "bar", "records", "settings"))

    def _prebuild_pages(self, *keys):
        """按顺序、间隔着预建页面，避免集中在一起卡顿"""
        keys = list(keys)
        if not keys:
            return
        k = keys.pop(0)
        try:
            if k != getattr(self, "_current_page", None):
                self._ensure_page(k)
        except Exception:
            pass
        if keys:
            self.after(150, lambda: self._prebuild_pages(*keys))


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

    def _install_wndproc(self):
        """不再子类化窗口过程（保留空实现，兼容旧调用）。

        历史原因：以前无边框窗口是用 withdraw() 把窗口「藏起来」的，
        藏起来的窗口任务栏按钮叫不回来，所以必须拦截
        SC_MINIMIZE / SC_RESTORE 自己处理。

        现在改成系统原生最小化（窗口仍然存活，只是最小化了），
        Windows 本来就能正确处理任务栏按钮的 最小化/还原，
        再拦截反而出问题：
          - 点任务栏还原时，如果窗口是被系统/任务栏最小化的，
            _minimized 标志是 False，消息被 return 0 吞掉，
            窗口就永远卡在最小化状态出不来了；
          - 点任务栏最小化也可能被吞掉。
        所以这里直接不拦截，全部交给 Windows 原生处理。
        """
        return

    def _uninstall_wndproc(self):
        """退出前恢复原窗口过程，防止窗口销毁后回调悬空导致闪退"""
        try:
            if getattr(self, "_orig_wndproc", 0):
                import ctypes
                user32 = ctypes.windll.user32
                user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
                user32.SetWindowLongPtrW.restype = ctypes.c_void_p
                user32.SetWindowLongPtrW(int(self.winfo_id()), -4, self._orig_wndproc)
                self._orig_wndproc = 0
        except Exception:
            pass

    # ---------- 全局热键 ----------

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
        """窗口显示后要做的几件事（任务栏样式 + 热键）"""
        self._enable_taskbar()
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

    # ---------- 无边框窗口：拖动 & 边缘调整大小 ----------

    def _drag_start(self, event):
        self._drag_x = event.x_root - self.winfo_x()
        self._drag_y = event.y_root - self.winfo_y()

    def _drag_move(self, event):
        try:
            self.geometry(f"+{event.x_root - self._drag_x}+{event.y_root - self._drag_y}")
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

    # ================= 界面 =================

    def _build_ui(self):
        self.configure(fg_color=BG)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # ---- 顶部标题条（无边框：可拖动 + 窗口控制按钮）----
        header = ctk.CTkFrame(self, height=44, corner_radius=0, fg_color=HEADER)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(1, weight=1)

        title_lbl = ctk.CTkLabel(header, text="🍃  StatGI",
                                 font=(FONT, 18, "bold"), text_color=TEXT)
        title_lbl.pack(side="left", padx=16)

        self.status_label = ctk.CTkLabel(header, text="未开始",
                                         font=(FONT, 15, "bold"), text_color=BAD)
        self.status_label.pack(side="left", padx=14)

        close_btn = ctk.CTkButton(
            header, text="✕", width=36, height=26, corner_radius=RADIUS_BTN, font=(FONT, 16),
            fg_color="transparent", hover_color="#3A2A2A", text_color=TEXT, command=self.on_close,
        )
        close_btn.pack(side="right", padx=(0, 10), pady=9)
        min_btn = ctk.CTkButton(
            header, text="─", width=36, height=26, corner_radius=RADIUS_BTN, font=(FONT, 16),
            fg_color="transparent", hover_color=BTN_HOVER, text_color=TEXT, command=self._minimize_to_tray,
        )
        min_btn.pack(side="right", padx=(0, 2), pady=9)

        # 按住标题条拖动窗口
        for w in (header, title_lbl):
            w.bind("<Button-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)

        # ---- 主体：左侧栏 + 内容区（透明，露出自定义背景）----
        body = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)

        # 左侧导航栏
        self.sidebar = ctk.CTkFrame(body, width=180, corner_radius=0, fg_color=SIDEBAR)
        self.sidebar.grid(row=0, column=0, sticky="nsw")
        self.sidebar.grid_propagate(False)

        # 顶部留白
        # （原来这里是 Logo「🍃 原神收益统计器 / StatGI」和日期，已按要求去掉，
        #   下面的选项会自动往上补位）
        ctk.CTkFrame(self.sidebar, height=10, fg_color="transparent").pack(fill="x")

        self.nav_btns = {}
        for key, icon, label in [
            ("launch", "🚀", "启动"),
            ("home", "📊", "今日统计"),
            ("bar", "📶", "收益统计条"),
            ("records", "📋", "收益记录"),
            ("settings", "⚙", "设置"),
        ]:
            btn = ctk.CTkButton(
                self.sidebar, text=f"{icon}  {label}",
                font=(FONT, 16),
                height=40, corner_radius=RADIUS_BTN,
                fg_color="transparent", hover_color=NAV_ON,
                text_color=DIM, anchor="w",
                command=lambda k=key: self._show_page(k),
            )
            btn.pack(fill="x", padx=10, pady=2)
            self.nav_btns[key] = btn

        ctk.CTkLabel(self.sidebar, text="V0.7", font=(FONT, 12), text_color=DIM).pack(side="bottom", pady=12)

        # 右侧内容区（透明）
        self.content = ctk.CTkFrame(body, corner_radius=0, fg_color="transparent")
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        # ---- 页面懒加载：启动时只建「启动」页，切到哪页才建哪页 ----
        # （全部一次性建要 1.7 秒以上，懒加载后首屏秒开）
        self._pages = {}
        self._page_builders = {
            "launch": self._build_page_launch,
            "home": self._build_page_home,
            "bar": self._build_page_bar,
            "records": self._build_page_records,
            "settings": self._build_page_settings,
        }
        self._ensure_page("launch")

        # ---- 无边框窗口的边缘调整大小条 ----
        right_strip = ctk.CTkFrame(self, width=6, cursor="sb_h_double_arrow", fg_color=BG)
        right_strip.grid(row=1, column=1, sticky="ns")
        right_strip.bind("<Button-1>", self._resize_start)
        right_strip.bind("<B1-Motion>", self._resize_right)

        bottom_strip = ctk.CTkFrame(self, height=6, cursor="sb_v_double_arrow", fg_color=BG)
        bottom_strip.grid(row=2, column=0, sticky="ew")
        bottom_strip.bind("<Button-1>", self._resize_start)
        bottom_strip.bind("<B1-Motion>", self._resize_bottom)

        corner = ctk.CTkFrame(self, width=6, height=6, cursor="size_nw_se", fg_color=BG)
        corner.grid(row=2, column=1, sticky="nsew")
        corner.bind("<Button-1>", self._resize_start)
        corner.bind("<B1-Motion>", self._resize_corner)

    # ---------- 自定义背景（图片铺底 + 半透明玻璃面板）----------
    #
    # CustomTkinter 没有真正的透明：每个控件都会用一层纯色把自己的区域盖住
    # （fg_color="transparent" 也只是「填父容器的颜色」）。
    # 所以这里用「玻璃贴图」的办法：
    #   把背景图上该控件所在的那一块裁下来，按面板透明度跟控件自身颜色混合，
    #   再贴回控件内部 —— 贴在自己底色之上、其它子控件（文字/图标）之下。
    # 这样除了文字和图标，其它地方都是半透明的，能看见底图。

    # 图形直接画在自己画布上的控件：贴图会盖住图形，
    # 改成把图垫在画布最底层（图片在图形下面、画布底色上面）
    _GLASS_ON_CANVAS = ("CTkSwitch", "CTkScrollbar", "CTkSlider")

    def _on_resize(self, event=None):
        """窗口尺寸变化时（去抖）重新生成背景，避免频繁重绘"""
        # <Configure> 绑在窗口上时，子控件的尺寸变化也会冒泡到这里，
        # 只处理窗口本身的变化（否则一切换页面就重算一遍背景，很卡）
        if event is not None and getattr(event, "widget", None) is not self:
            return
        if getattr(self, "_resize_after", None):
            try:
                self.after_cancel(self._resize_after)
            except Exception:
                pass
        self._resize_after = self.after(150, self._apply_background)

    # ---- 颜色小工具 ----

    @staticmethod
    def _as_hex(color):
        """把控件颜色统一成 '#RRGGBB'；transparent / None 返回 None"""
        if isinstance(color, (list, tuple)):
            color = color[-1] if color else None
        if not isinstance(color, str):
            return None
        if color.lower() == "transparent":
            return None
        if len(color) == 7 and color.startswith("#"):
            return color.upper()
        try:
            from PIL import ImageColor
            r, g, b = ImageColor.getrgb(color)[:3]
            return "#%02X%02X%02X" % (r, g, b)
        except Exception:
            return None

    @staticmethod
    def _rgb(hexcolor):
        h = hexcolor.lstrip("#")
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))

    def _w_fg(self, w):
        try:
            return self._as_hex(w.cget("fg_color"))
        except Exception:
            return None

    def _glass_alpha(self):
        """面板透明度：0=全透明，1=完全不透明"""
        try:
            return max(0.0, min(1.0, float(self.settings.get("panel_opacity", 0.5))))
        except Exception:
            return 0.5

    # ---- 玻璃底图（整窗，带缓存）----

    def _glass_base(self, tint, alpha, blur=False):
        cache = getattr(self, "_glass_cache", None)
        _a = round(alpha, 3)
        # 每张整窗底图约 1.8MB，换透明度时把上一批丢掉，避免堆积
        if cache is None or getattr(self, "_glass_cache_alpha", None) != _a:
            cache = {}
            self._glass_cache = cache
            self._glass_cache_alpha = _a
        key = (tint, bool(blur))
        hit = cache.get(key)
        if hit is not None:
            return hit
        from PIL import Image
        base = self._bg_img
        if blur:
            from PIL import ImageFilter
            base = base.filter(ImageFilter.GaussianBlur(10))
            base = Image.blend(base, Image.new("RGB", base.size, (12, 12, 14)), 0.35)
        if _a <= 0.001:
            out = base
        else:
            out = Image.blend(base, Image.new("RGB", base.size, self._rgb(tint)), _a)
        cache[key] = out
        return out

    # ---- 贴图 / 清理 ----

    def _glass_clear(self):
        """清掉所有玻璃层，并把改过的文字底色还原"""
        for w, info in list(getattr(self, "_glass_placed", {}).items()):
            lbl = info.get("lbl")
            if lbl is not None:
                try:
                    lbl.destroy()
                except Exception:
                    pass
            try:
                cv = getattr(w, "_canvas", None)
                if cv is not None and cv.winfo_exists():
                    cv.delete("glassbg")
                if info.get("canvas"):
                    w.delete("glassbg")
            except Exception:
                pass
        self._glass_placed = {}
        for t, orig in list(getattr(self, "_glass_text_orig", {}).items()):
            try:
                if t.winfo_exists():
                    t.configure(bg=orig)
            except Exception:
                pass
        self._glass_text_orig = {}
        for lbl in getattr(self, "_bg_layers", []):
            try:
                lbl.destroy()
            except Exception:
                pass
        self._bg_layers = []
        self._bg_photos = []

    def _glass_rect(self, w):
        return (w.winfo_rootx() - self.winfo_rootx(),
                w.winfo_rooty() - self.winfo_rooty(),
                w.winfo_width(), w.winfo_height())

    @staticmethod
    def _glass_crop(base, rect):
        """从整图里裁出 rect 位置的那一块（越界部分填黑）"""
        from PIL import Image
        ox, oy, cw, ch = rect
        if cw < 2 or ch < 2:
            return None
        crop = Image.new("RGB", (cw, ch), (0, 0, 0))
        sx, sy = max(0, ox), max(0, oy)
        ex, ey = min(base.width, ox + cw), min(base.height, oy + ch)
        if ex > sx and ey > sy:
            crop.paste(base.crop((sx, sy, ex, ey)), (sx - ox, sy - oy))
        return crop

    def _glass_fix_text(self, w, base):
        """控件内部的文字标签自带一块不透明底色，抹成该处玻璃的平均色"""
        for attr in ("_label", "_text_label", "_entry"):
            t = getattr(w, attr, None)
            if t is None:
                continue
            try:
                if not t.winfo_exists() or not t.winfo_ismapped():
                    continue
                rect = self._glass_rect(t)
                crop = self._glass_crop(base, rect)
                if crop is None:
                    continue
                from PIL import Image
                r, g, b = crop.resize((1, 1), Image.BILINEAR).getpixel((0, 0))
                if t not in self._glass_text_orig:
                    self._glass_text_orig[t] = t.cget("bg")
                t.configure(bg="#%02X%02X%02X" % (r, g, b))
            except Exception:
                pass

    def _glass_paint(self, w, tint, alpha, blur=False):
        """给控件贴一块玻璃（盖住它自己的底色，但在它的文字/图标下面）"""
        from PIL import ImageTk
        try:
            if not w.winfo_exists() or not w.winfo_ismapped():
                return
        except Exception:
            return
        rect = self._glass_rect(w)
        if rect[2] < 2 or rect[3] < 2:
            return
        key = ("L", tint, round(alpha, 3), bool(blur), rect)
        placed = getattr(self, "_glass_placed", None)
        if placed is None:
            placed = {}
            self._glass_placed = placed
        old = placed.get(w)
        if old is not None and old["key"] == key:
            try:
                if old["lbl"] is not None and old["lbl"].winfo_exists():
                    return
            except Exception:
                pass
        if old is not None:
            try:
                if old["lbl"] is not None:
                    old["lbl"].destroy()
            except Exception:
                pass
        crop = self._glass_crop(self._glass_base(tint, alpha, blur), rect)
        if crop is None:
            return
        photo = ImageTk.PhotoImage(crop)
        lbl = tk.Label(w, image=photo, bd=0, highlightthickness=0)
        lbl.place(x=0, y=0, relwidth=1, relheight=1)
        canvas = getattr(w, "_canvas", None)
        try:
            if canvas is not None and canvas.winfo_exists():
                # 只压过控件自己的底色层，文字/图标仍在它上面
                lbl.lift(canvas)
            else:
                lbl.lower()
        except Exception:
            pass
        placed[w] = {"lbl": lbl, "photo": photo, "key": key,
                     "tint": tint, "alpha": alpha, "blur": blur}
        self._glass_bind(w)
        self._glass_fix_text(w, self._glass_base(tint, alpha, blur))

    def _glass_paint_on_canvas(self, w, tint, alpha):
        """把玻璃垫在画布最底层（用于图形画在画布上的控件，如开关）"""
        from PIL import ImageTk
        canvas = getattr(w, "_canvas", None)
        if canvas is None:
            return
        try:
            if not canvas.winfo_exists() or not w.winfo_ismapped():
                return
        except Exception:
            return
        rect = self._glass_rect(w)
        if rect[2] < 2 or rect[3] < 2:
            return
        key = ("C", tint, round(alpha, 3), rect)
        placed = getattr(self, "_glass_placed", None)
        if placed is None:
            placed = {}
            self._glass_placed = placed
        old = placed.get(w)
        if old is not None and old["key"] == key:
            return
        crop = self._glass_crop(self._glass_base(tint, alpha), rect)
        if crop is None:
            return
        photo = ImageTk.PhotoImage(crop)
        try:
            canvas.delete("glassbg")
            canvas.create_image(0, 0, anchor="nw", image=photo, tags="glassbg")
            canvas.tag_lower("glassbg")
        except Exception:
            return
        placed[w] = {"lbl": None, "photo": photo, "key": key,
                     "tint": tint, "alpha": alpha, "blur": False,
                     "canvas": True}

    def _glass_paint_viewport(self, cv, tint, alpha, blur=False):
        """普通 tk 画布（可滚动区域的视口）：把图作为画布最底层的一项。

        画布会被滚动，所以图要按「视口原点」的坐标摆，滚动时再跟着挪。
        """
        from PIL import ImageTk
        try:
            if not cv.winfo_exists() or not cv.winfo_ismapped():
                return
        except Exception:
            return
        rect = self._glass_rect(cv)
        if rect[2] < 2 or rect[3] < 2:
            return
        key = ("V", tint, round(alpha, 3), bool(blur), rect)
        placed = getattr(self, "_glass_placed", None)
        if placed is None:
            placed = {}
            self._glass_placed = placed
        old = placed.get(cv)
        if old is not None and old["key"] == key:
            self._glass_reposition_viewport(cv)
            return
        crop = self._glass_crop(self._glass_base(tint, alpha, blur), rect)
        if crop is None:
            return
        photo = ImageTk.PhotoImage(crop)
        try:
            cv.delete("glassbg")
            cv.create_image(cv.canvasx(0), cv.canvasy(0), anchor="nw",
                            image=photo, tags="glassbg")
            cv.tag_lower("glassbg")
        except Exception:
            return
        placed[cv] = {"lbl": None, "photo": photo, "key": key,
                      "tint": tint, "alpha": alpha, "blur": blur,
                      "canvas": True, "viewport": True}

    @staticmethod
    def _glass_reposition_viewport(cv):
        try:
            cv.coords("glassbg", cv.canvasx(0), cv.canvasy(0))
        except Exception:
            pass

    # ---- 布局变化时只重贴动过的控件 ----

    def _glass_bind(self, w):
        if getattr(w, "_glass_bound", False):
            return
        try:
            w._glass_bound = True
            w.bind("<Configure>", lambda e, ww=w: self._glass_dirty(ww), add="+")
        except Exception:
            pass

    def _glass_dirty(self, w):
        if getattr(self, "_bg_busy", False) or not getattr(self, "_bg_img", None):
            return
        if getattr(self, "_glass_after", None) is None:
            dirty = getattr(self, "_glass_dirty_set", None)
            if dirty is None:
                dirty = set()
                self._glass_dirty_set = dirty
            dirty.add(w)
            try:
                self._glass_after = self.after(25, self._glass_flush)
            except Exception:
                pass
        else:
            dirty = getattr(self, "_glass_dirty_set", None)
            if dirty is None:
                dirty = set()
                self._glass_dirty_set = dirty
            dirty.add(w)

    def _glass_flush(self):
        """把这一轮动过的控件重贴一遍"""
        self._glass_after = None
        dirty = getattr(self, "_glass_dirty_set", set())
        self._glass_dirty_set = set()
        if getattr(self, "_bg_busy", False):
            return
        placed = getattr(self, "_glass_placed", {})
        for w in list(dirty):
            info = placed.get(w)
            try:
                if not w.winfo_exists():
                    placed.pop(w, None)
                    continue
            except Exception:
                placed.pop(w, None)
                continue
            if info is None:
                continue
            try:
                if info.get("viewport"):
                    self._glass_paint_viewport(w, info["tint"], info["alpha"], info.get("blur", False))
                elif info.get("canvas"):
                    self._glass_paint_on_canvas(w, info["tint"], info["alpha"])
                else:
                    self._glass_paint(w, info["tint"], info["alpha"], info.get("blur", False))
            except Exception:
                pass
        # 可滚动区域滚过之后，视口底图要跟着挪回原位
        for w, info in list(placed.items()):
            if info.get("viewport"):
                self._glass_reposition_viewport(w)

    # ---- 递归给整棵控件树贴玻璃 ----

    def _glass_walk(self, parent, tint, alpha, panel_alpha, blur=False, depth=0):
        if depth > 14:
            return
        try:
            children = parent.winfo_children()
        except Exception:
            return
        sidebar = getattr(self, "sidebar", None)
        for w in children:
            cls = type(w).__name__
            # 只处理 CustomTkinter 的控件。
            # 它们内部的画布 / 文字标签（CTkCanvas、tkinter.Label…）不能碰 ——
            # 往文字标签里再贴一层就会把字盖住，往画布上贴也会出问题。
            if cls.startswith("CTk"):
                if cls == "CTkCanvas":
                    continue
            elif cls in ("Canvas", "Frame", "Toplevel"):
                # 普通 tk 容器（可滚动框架内部就是这种画布）：只往下走，不贴图，
                # 否则里面的控件（设置页整页）都会漏掉
                if cls == "Canvas":
                    try:
                        self._glass_paint_viewport(w, tint, alpha, blur)
                    except Exception:
                        pass
                self._glass_walk(w, tint, alpha, panel_alpha, blur, depth + 1)
                continue
            else:
                continue
            # 侧边栏整块走「模糊」那条线
            _blur = blur or (w is sidebar and bool(self.settings.get("sidebar_glass", True)))
            own = self._w_fg(w)
            if own is not None:
                t, a = own, panel_alpha
            else:
                t, a = tint, alpha
            try:
                if cls in self._GLASS_ON_CANVAS:
                    self._glass_paint_on_canvas(w, t, a)
                    continue
                self._glass_paint(w, t, a, _blur)
            except Exception:
                pass
            self._glass_walk(w, t, a, panel_alpha, _blur, depth + 1)

    # ---- 总入口 ----

    def _apply_background(self):
        """根据设置应用背景：自定义图片 + 半透明面板；没图就是原来的纯色

        已经是增量刷新：图没换、控件没动过的不会重贴，
        否则每切一次页面都要重做一百多张贴图，卡得没法用。
        """
        if getattr(self, "_bg_busy", False):
            return
        self._bg_busy = True
        self._bg_sig = (str(self.settings.get("bg_image") or ""),
                        round(self._glass_alpha(), 3),
                        bool(self.settings.get("sidebar_glass", True)))
        try:
            img_path = self.settings.get("bg_image")
            has_img = bool(img_path) and Path(img_path).exists()
            if not has_img:
                self._glass_clear()
                self._bg_img = None
                self._bg_key = None
                self._glass_cache = {}
                return

            from PIL import Image, ImageTk
            self.update_idletasks()
            w = max(100, self.winfo_width())
            h = max(100, self.winfo_height())
            key = (str(img_path), w, h)
            if getattr(self, "_bg_key", None) != key or getattr(self, "_bg_img", None) is None:
                # 图或窗口尺寸变了：整体重来一次
                self._glass_clear()
                img = Image.open(img_path).convert("RGB")
                # cover 缩放：铺满窗口并居中裁剪
                scale = max(w / img.width, h / img.height)
                img = img.resize(
                    (max(1, int(img.width * scale)), max(1, int(img.height * scale))),
                    Image.LANCZOS,
                )
                x = (img.width - w) // 2
                y = (img.height - h) // 2
                self._bg_img = img.crop((x, y, x + w, y + h))
                self._bg_key = key
                self._glass_cache = {}

                # 整窗铺一张原图（结构层=完全透明，直接就是原图）
                photo = ImageTk.PhotoImage(self._bg_img)
                self._bg_photos.append(photo)
                lbl = tk.Label(self, image=photo, bd=0, highlightthickness=0)
                lbl.place(x=0, y=0, relwidth=1, relheight=1)
                lbl.lower()
                self._bg_layers.append(lbl)

            # 从窗口往下走：实色面板按「面板透明度」贴玻璃，
            # 透明容器继承上一层的颜色（所以页面空白处还是纯原图）
            self._glass_walk(self, self._as_hex(BG) or "#1C1C1C", 0.0,
                             self._glass_alpha(), False, 0)
            # 已经销毁的控件，把它的记录清掉
            placed = getattr(self, "_glass_placed", {})
            for _w in list(placed):
                try:
                    if not _w.winfo_exists():
                        info = placed.pop(_w)
                        if info.get("lbl") is not None:
                            info["lbl"].destroy()
                except Exception:
                    pass
        except Exception as e:
            # 不要静默失败：记下来，方便排查（以前这里被吞掉，
            # 导致「背景图没效果」这种问题很难查）
            import traceback
            self._bg_error = traceback.format_exc()
            print("[背景图] 应用失败:", e)
        finally:
            self._bg_busy = False

    # ---- 页面：启动（默认首页）----

    def _build_page_launch(self):
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        # 注意：这里不 grid()，交给 _show_page 统一控制
        # （否则启动时后台预建页面会「闪一下」再消失）
        page.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(page, text="启动", font=(FONT, 23, "bold"), text_color=ACCENT).grid(
            row=0, column=0, sticky="w", pady=(0, 12))

        # ---- 顶部：大标题 + 状态 + 装饰区 ----
        header = self._make_card(page)
        header.grid(row=1, column=0, sticky="ew")

        deco = ctk.CTkFrame(header, width=104, height=68, corner_radius=RADIUS_CARD,
                            fg_color=CARD_INNER, border_width=1, border_color=theme.BORDER)
        deco.pack(side="right", padx=(8, 12), pady=9)
        deco.pack_propagate(False)
        ctk.CTkLabel(deco, text="🍃", font=(FONT, 23)).pack(pady=(6, 0))
        ctk.CTkLabel(deco, text="StatGI V0.7", font=(FONT, 11, "bold"), text_color=ACCENT).pack()

        hl = ctk.CTkFrame(header, fg_color="transparent")
        hl.pack(side="left", fill="both", expand=True, padx=16, pady=8)
        ctk.CTkLabel(hl, text="🍃  StatGI", font=(FONT, 24, "bold"), text_color=TEXT).pack(anchor="w")
        _r1 = ctk.CTkFrame(hl, fg_color="transparent")
        _r1.pack(anchor="w")
        self.launch_status_label = ctk.CTkLabel(_r1, text="🟢 未开始", font=(FONT, 13, "bold"), text_color=BAD)
        self.launch_status_label.pack(side="left")
        self.launch_region_label = ctk.CTkLabel(_r1, text="　📍 自动检测游戏窗口", font=(FONT, 11), text_color=DIM)
        self.launch_region_label.pack(side="left")
        self.last_event_label = ctk.CTkLabel(hl, text="🕐 最后识别：—", font=(FONT, 11), text_color=DIM)
        self.last_event_label.pack(anchor="w")

        # ---- 功能卡片：横向长条（左图标 / 中标题说明 / 右按钮）----
        rows = ctk.CTkFrame(page, fg_color="transparent")
        rows.grid(row=2, column=0, sticky="nsew", pady=(12, 0))
        page.grid_rowconfigure(2, weight=1)
        rows.grid_columnconfigure(0, weight=1)

        self.start_card, self.start_card_title, self.start_card_btn = self._make_row_card(
            rows, "▶", "开始监测", "自动找到游戏窗口并识别掉落收益",
            "开始", self.on_start_stop, accent=True)
        self.start_card.pack(fill="x", pady=(0, 6))

        # 「清空」卡片：第 1 种浮动下拉选清空内容 + 右边按钮执行
        self._make_clear_card(rows)

        # 「重新框选」折叠区：第 2 种（点标题原地展开，里面含诊断截图）
        _acc = Accordion(rows, "🎯", "重新框选",
                         "手动指定要识别的屏幕区域；里面还有「诊断截图」（一般都不用）",
                         self._build_reselect_body, on_change=self._apply_background)
        _acc.pack(fill="x", pady=(0, 6))
        return page

    def _build_reselect_body(self, parent):
        """「重新框选」展开后的内容：重新框选 + 诊断截图"""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(0, 8))
        ctk.CTkButton(
            row, text="🎯 重新框选", font=(FONT, 15), height=36, corner_radius=RADIUS_BTN,
            fg_color=BTN, hover_color=BTN_HOVER, command=self.on_reselect,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            row, text="📷 诊断截图", font=(FONT, 15), height=36, corner_radius=RADIUS_BTN,
            fg_color=BTN, hover_color=BTN_HOVER, command=self.on_debug_screenshot,
        ).pack(side="left")
        ctk.CTkLabel(
            parent,
            text="· 重新框选：手动圈出识别区域（平时不用，程序会自动找游戏窗口）\n"
                 "· 诊断截图：用来查看识别区域里到底有什么文字（一般不用）",
            font=(FONT, 12), text_color=DIM, justify="left",
        ).pack(anchor="w", padx=14, pady=(0, 12))

    def _make_clear_card(self, parent):
        """清空卡片：第 1 种浮动下拉选「清空数据 / 清空时间 / 都清空」，右边按钮执行"""
        card = ctk.CTkFrame(parent, corner_radius=RADIUS_CARD, fg_color=CARD,
                            border_width=1, border_color=theme.BORDER)
        ctk.CTkButton(
            card, text="清空", font=(FONT, 15), width=84, height=34,
            corner_radius=RADIUS_BTN, fg_color=DANGER, hover_color=DANGER_HOVER,
            text_color="#FFFFFF", command=self._on_clear_selected,
        ).pack(side="right", padx=(10, 14), pady=9)

        self.clear_dd = FloatingDropdown(
            card, values=["清空今日数据", "清空监测时间", "清空数据和时间"],
            height=34, font_size=14, min_width=110)
        self.clear_dd.configure(width=176)
        self.clear_dd.set("清空今日数据")
        self.clear_dd.pack(side="right", padx=(8, 0), pady=9)
        self.clear_choice = self.clear_dd._var      # 兼容旧引用

        ic = ctk.CTkFrame(card, width=42, height=42, corner_radius=12, fg_color=CARD_INNER)
        ic.pack(side="left", padx=(14, 12), pady=9)
        ic.pack_propagate(False)
        ctk.CTkLabel(ic, text="🧹", font=(FONT, 20), text_color=ACCENT).place(
            relx=0.5, rely=0.5, anchor="center")
        mid = ctk.CTkFrame(card, fg_color="transparent")
        mid.pack(side="left", fill="both", expand=True, pady=9)
        ctk.CTkLabel(mid, text="清空", font=(FONT, 16, "bold"), text_color=TEXT, anchor="w").pack(anchor="w")
        ctk.CTkLabel(mid, text="选好要清空的内容，再点右边按钮（收益记录不受影响）",
                     font=(FONT, 12), text_color=DIM, anchor="w").pack(anchor="w", pady=(2, 0))
        card.pack(fill="x", pady=(0, 6))
        return card

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

    def _make_row_card(self, parent, icon, title, desc, btn_text, command, accent=False):
        """横向长条卡片：[图标小卡片] [标题 + 说明] ......... [按钮]

        返回 (卡片, 标题标签, 按钮)
        """
        card = ctk.CTkFrame(parent, corner_radius=RADIUS_CARD, fg_color=CARD,
                            border_width=1, border_color=theme.BORDER)

        btn = ctk.CTkButton(
            card, text=btn_text, font=(FONT, 15), width=94, height=38,
            corner_radius=RADIUS_BTN,
            fg_color=(ACCENT if accent else BTN),
            hover_color=(ACCENT_DARK if accent else BTN_HOVER),
            text_color=("#FFFFFF" if accent else TEXT),
            command=command,
        )
        btn.pack(side="right", padx=(10, 14), pady=9)

        ic = ctk.CTkFrame(card, width=46, height=46, corner_radius=13,
                          fg_color=(ACCENT if accent else CARD_INNER))
        ic.pack(side="left", padx=(14, 12), pady=9)
        ic.pack_propagate(False)
        _il = ctk.CTkLabel(ic, text=icon, font=(FONT, 24),
                           text_color=("#FFFFFF" if accent else ACCENT))
        _il.place(relx=0.5, rely=0.5, anchor="center")

        mid = ctk.CTkFrame(card, fg_color="transparent")
        mid.pack(side="left", fill="both", expand=True, pady=9)
        tl = ctk.CTkLabel(mid, text=title, font=(FONT, 18, "bold"), text_color=TEXT, anchor="w")
        tl.pack(anchor="w")
        ctk.CTkLabel(mid, text=desc, font=(FONT, 13), text_color=DIM, anchor="w").pack(anchor="w", pady=(2, 0))

        def _click(_e=None):
            try:
                command()
            except Exception:
                pass

        # 整行都能点（按钮自己已绑定，不重复绑）
        for _w in (card, ic, _il, mid, tl):
            try:
                _w.bind("<Button-1>", _click)
                _w.configure(cursor="hand2")
            except Exception:
                pass
        return card, tl, btn

    # ---- 页面：今日统计 ----

    def _build_page_home(self):
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        # 注意：这里不 grid()，交给 _show_page 统一控制
        # （否则启动时后台预建页面会「闪一下」再消失）
        page.grid_columnconfigure(0, weight=1)

        # 上排三个卡片：摩拉 / 狗粮 / 监测时间
        cards = ctk.CTkFrame(page, fg_color="transparent")
        cards.grid(row=0, column=0, sticky="ew")
        for i in range(3):
            cards.grid_columnconfigure(i, weight=1)

        mora_card = self._make_card(cards)
        mora_card.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        ctk.CTkLabel(mora_card, text="💰 今日摩拉", font=(FONT, 15), text_color=DIM).pack(pady=(14, 2))
        self.mora_label = ctk.CTkLabel(mora_card, text="0", font=(FONT, 36, "bold"), text_color=ACCENT)
        self.mora_label.pack(pady=(0, 14))

        art_card = self._make_card(cards)
        art_card.grid(row=0, column=1, sticky="nsew", padx=6)
        ctk.CTkLabel(art_card, text="💠 狗粮（圣遗物）", font=(FONT, 15), text_color=DIM).pack(pady=(14, 2))
        self.artifact_label = ctk.CTkLabel(art_card, text="×0", font=(FONT, 36, "bold"), text_color=ACCENT)
        self.artifact_label.pack(pady=(0, 14))

        time_card = self._make_card(cards)
        time_card.grid(row=0, column=2, sticky="nsew", padx=(6, 0))
        ctk.CTkLabel(time_card, text="⏱ 监测时间", font=(FONT, 15), text_color=DIM).pack(pady=(14, 2))
        self.time_label = ctk.CTkLabel(time_card, text="00:00:00", font=(FONT, 28, "bold"), text_color=TEXT)
        self.time_label.pack(pady=(6, 14))

        # 素材区（双列：怪物素材 | 普通材料）
        recent = self._make_card(page)
        recent.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        page.grid_rowconfigure(1, weight=1)

        head2 = ctk.CTkFrame(recent, fg_color="transparent")
        head2.pack(fill="x", padx=14, pady=(12, 2))
        ctk.CTkLabel(head2, text="⚔ 材料", font=(FONT, 17, "bold"), text_color=ACCENT).pack(side="left")
        # 「查看明细」按钮：原「素材明细」页已合并到这里，点它就地展开明细
        self.detail_toggle_btn = ctk.CTkButton(
            head2, text="查看明细", font=(FONT, 13), width=84, height=26,
            corner_radius=RADIUS_BTN, fg_color=BTN, hover_color=BTN_HOVER,
            text_color=TEXT, command=self._toggle_material_detail,
        )
        self.detail_toggle_btn.pack(side="right")

        # 简要列表（默认显示）
        self.mat_scroll = ctk.CTkScrollableFrame(recent, corner_radius=RADIUS_INNER, fg_color=CARD_INNER)
        self.mat_scroll.pack(fill="both", expand=True, padx=10, pady=(2, 10))

        # 明细视图（默认隐藏，点「查看明细」展开）
        self.detail_frame = ctk.CTkFrame(recent, fg_color="transparent")
        self.detail_scroll = ctk.CTkScrollableFrame(
            self.detail_frame, corner_radius=RADIUS_INNER, fg_color=CARD_INNER)
        self.detail_scroll.pack(fill="both", expand=True)
        self.detail_total_label = ctk.CTkLabel(self.detail_frame, text="", font=(FONT, 15), text_color=DIM)
        self.detail_total_label.pack(anchor="w", padx=6, pady=(6, 0))
        self.detail_scroll2 = self.detail_scroll   # 兼容旧引用
        self._detail_shown = False
        return page

    # ---- 材料明细 展开/收起（原「素材明细」页已合并进「今日统计」）----

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

    # ---- 页面：收益统计条 ----

    def _build_page_bar(self):
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        # 注意：这里不 grid()，交给 _show_page 统一控制
        # （否则启动时后台预建页面会「闪一下」再消失）
        page.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(page, text="收益统计条", font=(FONT, 23, "bold"), text_color=ACCENT).grid(
            row=0, column=0, sticky="w", pady=(0, 12))

        card = self._make_card(page)
        card.grid(row=1, column=0, sticky="ew")
        ctk.CTkLabel(
            card, text="直播间小窗口：摩拉 / 材料 / 狗粮 三个格子，图标在上、数量在下。",
            font=(FONT, 16), text_color=TEXT,
        ).pack(padx=20, pady=(16, 4))
        ctk.CTkLabel(
            card, text="· 打开后可以随便拖动位置，放到直播间角落\n"
                       "· 三个格子的图标已内置（默认图标）\n"
                       "· OBS 里用「窗口捕获」选「收益统计条」窗口即可上屏",
            font=(FONT, 15), text_color=DIM, justify="left",
        ).pack(padx=20, pady=(0, 12))
        self.bar_btn = ctk.CTkButton(
            card, text="📶 打开统计条", font=(FONT, 17),
            height=44, corner_radius=8, fg_color=ACCENT, hover_color=ACCENT_DARK,
            text_color="#FFFFFF", command=self.on_stat_bar_toggle,
        )
        self.bar_btn.pack(padx=20, pady=(4, 18))

        # ---- 子选项：统计条透明度 ----
        op_card = self._make_card(page)
        op_card.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        ctk.CTkLabel(op_card, text="🌓 统计条透明度", font=(FONT, 17, "bold"),
                     text_color=ACCENT).pack(anchor="w", padx=20, pady=(14, 2))
        ctk.CTkLabel(op_card, text="往左拉更透明，放在直播画面上不容易挡到游戏画面。",
                     font=(FONT, 15), text_color=DIM).pack(anchor="w", padx=20, pady=(0, 8))

        op_row = ctk.CTkFrame(op_card, fg_color="transparent")
        op_row.pack(fill="x", padx=20, pady=(0, 16))
        self.bar_opacity_label = ctk.CTkLabel(op_row, text="", font=(FONT, 16, "bold"),
                                              text_color=TEXT, width=56)
        self.bar_opacity_label.pack(side="right", padx=(12, 0))
        _cur_op = float((self.settings.get("stat_bar") or {}).get("opacity", 1.0))
        _cur_op = max(0.2, min(1.0, _cur_op))
        self.bar_opacity_slider = ctk.CTkSlider(
            op_row, from_=0.2, to=1.0, number_of_steps=16,
            command=self._on_bar_opacity_change,
        )
        self.bar_opacity_slider.set(_cur_op)
        self.bar_opacity_slider.pack(side="left", fill="x", expand=True)
        self.bar_opacity_label.configure(text=f"{int(round(_cur_op * 100))}%")

        # ---- 子选项：显示哪几个格子 ----
        slot_card = self._make_card(page)
        slot_card.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        ctk.CTkLabel(slot_card, text="📶 显示哪几个格子", font=(FONT, 17, "bold"),
                     text_color=ACCENT).pack(anchor="w", padx=20, pady=(14, 2))
        ctk.CTkLabel(slot_card, text="不想显示的直接关掉即可（改完立即生效）。",
                     font=(FONT, 15), text_color=DIM).pack(anchor="w", padx=20, pady=(0, 8))
        _bar = self.settings.get("stat_bar") or {}
        self._slot_vars = {}
        for _key, _name in (("slot1", "💰 摩拉"), ("slot2", "⚔ 材料"), ("slot3", "💠 狗粮")):
            _v = ctk.BooleanVar(value=bool(_bar.get("show_" + _key, True)))
            ctk.CTkSwitch(
                slot_card, text=_name, variable=_v, onvalue=True, offvalue=False,
                font=(FONT, 16), fg_color=SWITCH_OFF, progress_color=ACCENT, text_color=TEXT,
                command=self._on_any_setting_change,
            ).pack(anchor="w", padx=20, pady=(2, 2))
            self._slot_vars[_key] = _v
        ctk.CTkFrame(slot_card, height=10, fg_color="transparent").pack()
        return page

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

    # ---- 页面：收益记录（每次「开始监测→停止监测」记一条）----

    def _build_page_records(self):
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        # 注意：这里不 grid()，交给 _show_page 统一控制
        # （否则启动时后台预建页面会「闪一下」再消失）
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)

        head = ctk.CTkFrame(page, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ctk.CTkLabel(head, text="收益记录", font=(FONT, 23, "bold"), text_color=ACCENT).pack(side="left")
        ctk.CTkButton(
            head, text="🗑 清空记录", font=(FONT, 15), width=100, height=30,
            corner_radius=RADIUS_BTN, fg_color=DANGER, hover_color=DANGER_HOVER,
            command=self.on_clear_records,
        ).pack(side="right")

        self.records_scroll = ctk.CTkScrollableFrame(page, corner_radius=RADIUS_CARD, fg_color=CARD)
        self.records_scroll.grid(row=1, column=0, sticky="nsew")
        self.records_scroll.grid_columnconfigure(0, weight=1)

        self._rec_open = set()
        self._rec_widgets = {}
        self._rebuild_records()
        return page

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
            return
        # 最新的排在最上面
        for idx in range(len(items) - 1, -1, -1):
            self._make_record_card(sc, idx, items[idx])

    def _make_record_card(self, parent, idx, rec):
        card = ctk.CTkFrame(parent, fg_color=CARD_INNER, corner_radius=10)
        card.pack(fill="x", padx=8, pady=4)

        top = ctk.CTkFrame(card, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(10, 2))
        ctk.CTkLabel(top, text=f"{rec.get('start', '')}  →  {rec.get('end', '')}",
                     font=(FONT, 13), text_color=DIM).pack(side="left")
        ctk.CTkLabel(top, text=self._fmt_dur(rec.get("seconds", 0)),
                     font=(FONT, 15, "bold"), text_color=ACCENT).pack(side="right")

        mid = ctk.CTkFrame(card, fg_color="transparent")
        mid.pack(fill="x", padx=12, pady=(2, 6))
        ctk.CTkLabel(mid, text=f"💰 {int(rec.get('mora', 0)):,}", font=(FONT, 16), text_color=TEXT).pack(
            side="left", padx=(0, 18))
        ctk.CTkLabel(mid, text=f"💠 狗粮 ×{int(rec.get('artifact', 0))}", font=(FONT, 16), text_color=TEXT).pack(
            side="left", padx=(0, 18))
        _mats = rec.get("materials") or {}
        ctk.CTkLabel(mid, text=f"⚔ 材料 {len(_mats)} 种 / {sum(_mats.values())} 个",
                     font=(FONT, 16), text_color=TEXT).pack(side="left")

        # 明细区（默认收起）
        detail = ctk.CTkFrame(card, fg_color="transparent")
        if _mats:
            for name, cnt in sorted(_mats.items(), key=lambda kv: -kv[1]):
                r = ctk.CTkFrame(detail, fg_color="transparent")
                r.pack(fill="x", pady=1)
                ctk.CTkLabel(r, text=name, font=(FONT, 15), text_color=TEXT).pack(side="left")
                ctk.CTkLabel(r, text=f"×{cnt}", font=(FONT, 15, "bold"), text_color=ACCENT).pack(side="right")
        else:
            ctk.CTkLabel(detail, text="（这段时间没有识别到材料）",
                         font=(FONT, 13), text_color=DIM).pack(anchor="w")

        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.pack(fill="x", padx=12, pady=(0, 10))
        btn = ctk.CTkButton(
            btn_row, text="查看明细 ▾", font=(FONT, 15), width=100, height=28,
            corner_radius=RADIUS_BTN, fg_color=BTN, hover_color=BTN_HOVER,
            command=lambda i=idx: self._toggle_record_detail(i),
        )
        btn.pack(side="right")

        self._rec_widgets[idx] = (detail, btn)
        if idx in getattr(self, "_rec_open", set()):
            detail.pack(fill="x", padx=12, pady=(0, 8))
            btn.configure(text="收起明细 ▴")

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

    def on_clear_records(self):
        if not messagebox.askyesno("确认", "确定清空所有收益记录吗？\n（今日统计的数据不受影响）"):
            return
        sessions.clear_sessions()
        self._rec_open = set()
        self._rebuild_records()
        messagebox.showinfo("已清空", "收益记录已清空")

    # ---- 页面：设置（标签页 + 分组卡片）----

    def _build_page_settings(self):
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        # 注意：这里不 grid()，交给 _show_page 统一控制
        # （否则启动时后台预建页面会「闪一下」再消失）
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(page, text="设置", font=(FONT, 23, "bold"), text_color=ACCENT).grid(
            row=0, column=0, sticky="w", pady=(0, 10))

        # ---- 标签栏 ----
        self.settings_tab_var = ctk.StringVar(value="识别")
        ctk.CTkSegmentedButton(
            page, values=["识别", "统计", "外观", "关于"], variable=self.settings_tab_var,
            font=(FONT, 14), fg_color=BTN, selected_color=ACCENT, selected_hover_color=ACCENT_DARK,
            text_color=TEXT, text_color_disabled=DIM, command=self._on_settings_tab,
        ).grid(row=1, column=0, sticky="ew", pady=(0, 10))

        holder = ctk.CTkFrame(page, fg_color="transparent")
        holder.grid(row=2, column=0, sticky="nsew")
        holder.grid_columnconfigure(0, weight=1)
        holder.grid_rowconfigure(0, weight=1)
        self._settings_tabs = {}
        for _name in ("识别", "统计", "外观", "关于"):
            _f = ctk.CTkScrollableFrame(holder, corner_radius=0, fg_color=BG)
            _f.grid(row=0, column=0, sticky="nsew")
            _f.grid_columnconfigure(0, weight=1)
            self._settings_tabs[_name] = _f

        # ================= 识别 =================
        t = self._settings_tabs["识别"]

        h = self._make_setting_card(t, "⏱", "检测间隔", "每多少毫秒检查一次画面（10~5000，默认 50）")
        self.tick_entry = ctk.CTkEntry(h, font=(FONT, 14), height=34, width=104,
                                       fg_color=CARD_INNER, text_color=TEXT, border_color=BTN_HOVER)
        self.tick_entry.insert(0, str(int(self.settings.get("tick_interval", 50))))
        self.tick_entry.pack(side="right")
        self.tick_entry.bind("<KeyRelease>", self._on_tick_change)
        self.tick_entry.bind("<FocusOut>", self._on_any_setting_change)

        h = self._make_setting_card(t, "🎚", "画面变化灵敏度", "越灵敏识别越快，太灵敏会耗电")
        self.change_var = ctk.StringVar(value=str(self.settings.get("change_level", "中")))
        self.change_dd = FloatingDropdown(h, ["高", "中", "低"], variable=self.change_var,
                                          command=self._on_any_setting_change, font_size=14)
        self.change_dd.pack(fill="x")

        h = self._make_setting_card(t, "🔁", "防重复窗口", "同一提示消失多久后再出现才算新掉落")
        _ev = str(self.settings.get("event_end_window", 1.5)).replace("秒", "").strip()
        self.event_var = ctk.StringVar(value=f"{_ev} 秒")
        self.event_dd = FloatingDropdown(h, ["1.0 秒", "1.5 秒", "2.5 秒"], variable=self.event_var,
                                         command=self._on_any_setting_change, font_size=14)
        self.event_dd.pack(fill="x")

        h = self._make_setting_card(t, "🔍", "文字识别频率", "越快响应越及时，越慢越省电")
        self.ocr_var = ctk.StringVar(
            value={150: "快", 250: "标准", 500: "慢"}.get(int(self.settings.get("ocr_interval", 250)), "标准"))
        self.ocr_dd = FloatingDropdown(h, ["快", "标准", "慢"], variable=self.ocr_var,
                                       command=self._on_any_setting_change, font_size=14)
        self.ocr_dd.pack(fill="x")

        h = self._make_setting_card(t, "➕", "自动登记新材料", "遇到材料库里没有的名字时自动加进材料库")
        self.auto_reg_var = ctk.BooleanVar(value=bool(self.settings.get("auto_register_material", True)))
        ctk.CTkSwitch(h, text="", variable=self.auto_reg_var, onvalue=True, offvalue=False,
                      width=54, fg_color=SWITCH_OFF, progress_color=ACCENT,
                      command=self._on_any_setting_change).pack(side="right")

        # ================= 统计 =================
        t = self._settings_tabs["统计"]

        # 识别内容：第 2 种折叠区（三个开关合并进来）
        self._acc_enable = Accordion(
            t, "🎯", "识别内容", "想统计什么就开什么（点这里展开）", self._build_enable_body,
            on_change=self._apply_background)
        self._acc_enable.pack(fill="x", pady=(0, 8))

        h = self._make_setting_card(t, "✖", "点右上角 ✕ 时", "关闭窗口时的行为")
        _cb = {"ask": "每次询问", "tray": "最小化到托盘", "exit": "直接退出"}.get(
            self.settings.get("close_behavior", "ask"), "每次询问")
        self.close_btn_var = ctk.StringVar(value=_cb)
        self.close_dd = FloatingDropdown(
            h, ["每次询问", "最小化到托盘", "直接退出"], variable=self.close_btn_var,
            command=self._on_any_setting_change, font_size=14)
        self.close_dd.pack(fill="x")

        h = self._make_setting_card(t, "🎯", "只在原神前台时识别", "切到别的应用就暂停，回到原神自动继续")
        self.only_foreground_var = ctk.BooleanVar(value=bool(self.settings.get("only_foreground", True)))
        ctk.CTkSwitch(h, text="", variable=self.only_foreground_var, onvalue=True, offvalue=False,
                      width=54, fg_color=SWITCH_OFF, progress_color=ACCENT,
                      command=self._on_any_setting_change).pack(side="right")

        # 换日时间：输入框（自己填 0~23）
        h = self._make_setting_card(t, "🌙", "换日时间", "填 0~23。挂机挂过零点的话，往后填几小时就不会中途归零")
        try:
            _ro = int(self.settings.get("rollover_hour", 0)) % 24
        except Exception:
            _ro = 0
        self.rollover_entry = ctk.CTkEntry(h, font=(FONT, 14), height=34, width=84,
                                           fg_color=CARD_INNER, text_color=TEXT, border_color=BTN_HOVER)
        self.rollover_entry.insert(0, str(_ro))
        ctk.CTkLabel(h, text="点", font=(FONT, 14), text_color=DIM).pack(side="right")
        self.rollover_entry.pack(side="right", padx=(0, 6))
        self.rollover_var = ctk.StringVar(value=str(_ro))

        def _ro_edit(_e=None):
            try:
                self.rollover_var.set(self.rollover_entry.get().strip())
            except Exception:
                pass
            self._on_tick_change()

        self.rollover_entry.bind("<KeyRelease>", _ro_edit)
        self.rollover_entry.bind("<FocusOut>", self._on_any_setting_change)

        # 全局热键（按一下就设定）
        h = self._make_setting_card(t, "⌨", "全局热键（开始/停止监测）", "点按钮后按下想用的键（Esc 取消）")
        self.hotkey_btn = ctk.CTkButton(
            h, text=str(self.settings.get("hotkey", "关闭")), font=(FONT, 14),
            height=34, corner_radius=RADIUS_BTN, fg_color=BTN, hover_color=BTN_HOVER,
            command=self._start_hotkey_capture,
        )
        self.hotkey_btn.pack(fill="x")
        self.hotkey_var = ctk.StringVar(value=str(self.settings.get("hotkey", "关闭")))

        # ================= 外观 =================
        t = self._settings_tabs["外观"]

        h = self._make_setting_card(t, "🎨", "背景颜色", "窗口背景色")
        cur_bg = self.settings.get("bg_color", "经典深黑")
        if cur_bg not in theme.BG_PRESETS:
            self._custom_bg_hex = cur_bg
        self.bg_var = ctk.StringVar(value=cur_bg if cur_bg in theme.BG_PRESETS else "自定义…")
        # 记住上一次选的预设（取消取色时用来回退）
        self._last_bg_sel = cur_bg if cur_bg in theme.BG_PRESETS else "经典深黑"
        self.bg_dd = FloatingDropdown(
            h, list(theme.BG_PRESETS.keys()) + ["自定义…"], variable=self.bg_var,
            command=self._on_pick_bg_color, font_size=14)
        self.bg_dd.pack(fill="x")

        h = self._make_setting_card(t, "🌈", "强调色", "按钮、选中项、数字高亮的颜色")
        cur_ac = self.settings.get("accent_color", "经典蓝")
        if cur_ac not in theme.ACCENT_PRESETS:
            self._custom_accent_hex = cur_ac
        self.accent_var = ctk.StringVar(value=cur_ac if cur_ac in theme.ACCENT_PRESETS else "自定义…")
        self._last_accent_sel = cur_ac if cur_ac in theme.ACCENT_PRESETS else "经典蓝"
        self.accent_dd = FloatingDropdown(
            h, list(theme.ACCENT_PRESETS.keys()) + ["自定义…"], variable=self.accent_var,
            command=self._on_pick_accent_color, font_size=14)
        self.accent_dd.pack(fill="x")

        # 背景图片 + 毛玻璃：第 2 种折叠区
        self._acc_bg = Accordion(
            t, "🖼", "自定义背景图片", "选图片当窗口背景；可以调卡片透明度（含侧边栏和按钮）",
            self._build_bg_body, on_change=self._apply_background)
        self._acc_bg.pack(fill="x", pady=(0, 8))

        # OBS：第 2 种折叠区
        self._acc_obs = Accordion(
            t, "📺", "连接 OBS 直播覆盖", "点开可以看到开关和浏览器源地址",
            self._build_obs_body, on_change=self._apply_background)
        self._acc_obs.pack(fill="x", pady=(0, 8))

        # ================= 关于 =================
        t = self._settings_tabs["关于"]

        h = self._make_setting_card(t, "ℹ️", "StatGI V0.7（测试版）",
                                    "识别只靠文字（OCR），不读内存、不控制游戏\n"
                                    "防重复统计：同一个掉落提示只统计一次\n"
                                    "数据保存在程序旁边的 data 文件夹", wide=True)
        _upd = ctk.CTkFrame(h, fg_color="transparent")
        _upd.pack(fill="x")
        ctk.CTkButton(
            _upd, text="🔍 检测更新", font=(FONT, 14), height=34, width=130,
            corner_radius=8, fg_color=ACCENT, hover_color=ACCENT_DARK, text_color="#FFFFFF",
            command=self.on_check_update,
        ).pack(side="left")
        self.update_status_label = ctk.CTkLabel(_upd, text="", font=(FONT, 13), text_color=DIM)
        self.update_status_label.pack(side="left", padx=10)
        ctk.CTkLabel(h, text="检测更新会访问 GitHub Releases，需要联网。",
                     font=(FONT, 12), text_color=DIM).pack(anchor="w", pady=(6, 0))

        if self.settings.get("developer_mode", False):
            self._build_dev_card(t, 0)

        self._on_settings_tab("识别")
        return page

    # ---------- 折叠区域的内部内容 ----------

    def _build_enable_body(self, parent):
        """「识别内容」展开后：摩拉 / 怪物素材 / 圣遗物 三个开关"""
        self.enable_mora_var = ctk.BooleanVar(value=bool(self.settings.get("enable_mora", True)))
        self.enable_mat_var = ctk.BooleanVar(value=bool(self.settings.get("enable_material", True)))
        self.enable_art_var = ctk.BooleanVar(value=bool(self.settings.get("enable_artifact", True)))
        for var, text, tip in (
            (self.enable_mora_var, "💰 识别摩拉", "统计掉落提示里的摩拉"),
            (self.enable_mat_var, "⚔ 识别怪物素材", "统计怪物掉落的各种素材"),
            (self.enable_art_var, "💠 识别圣遗物（狗粮）", "统计捡到的圣遗物数量"),
        ):
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", padx=14, pady=3)
            ctk.CTkLabel(row, text=text, font=(FONT, 15), text_color=TEXT, anchor="w").pack(side="left")
            ctk.CTkLabel(row, text=tip, font=(FONT, 12), text_color=DIM, anchor="w").pack(
                side="left", padx=(10, 0))
            ctk.CTkSwitch(row, text="", variable=var, onvalue=True, offvalue=False,
                          width=54, fg_color=SWITCH_OFF, progress_color=ACCENT,
                          command=self._on_any_setting_change).pack(side="right")
        ctk.CTkFrame(parent, height=8, fg_color="transparent").pack()

    def _build_bg_body(self, parent):
        """「自定义背景图片」展开后：选图片 + 清除 + 毛玻璃开关"""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(0, 6))
        ctk.CTkButton(
            row, text="🖼 选择图片…", font=(FONT, 14), height=32, width=130,
            fg_color=BTN, hover_color=BTN_HOVER, command=self._choose_bg_image,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            row, text="✖ 清除背景", font=(FONT, 14), height=32, width=130,
            fg_color=DANGER, hover_color=DANGER_HOVER, command=self._clear_bg_image,
        ).pack(side="left", padx=(0, 12))
        _cur_bg_file = Path(self.settings.get("bg_image") or "").name if self.settings.get("bg_image") else ""
        self._bg_img_label = ctk.CTkLabel(
            row, text=f"当前：{_cur_bg_file}" if _cur_bg_file else "未设置（纯色背景）",
            font=(FONT, 13), text_color=DIM)
        self._bg_img_label.pack(side="left")

        row2 = ctk.CTkFrame(parent, fg_color="transparent")
        row2.pack(fill="x", padx=14, pady=(2, 10))
        ctk.CTkLabel(row2, text="左侧栏毛玻璃效果", font=(FONT, 15), text_color=TEXT).pack(side="left")
        ctk.CTkLabel(row2, text="需要先设置背景图片（模糊+压暗，模拟磨砂质感）",
                     font=(FONT, 12), text_color=DIM).pack(side="left", padx=(10, 0))
        self.glass_var = ctk.BooleanVar(value=bool(self.settings.get("sidebar_glass", True)))
        ctk.CTkSwitch(row2, text="", variable=self.glass_var, onvalue=True, offvalue=False,
                      width=54, fg_color=SWITCH_OFF, progress_color=ACCENT,
                      command=self._on_any_setting_change).pack(side="right")

        row3 = ctk.CTkFrame(parent, fg_color="transparent")
        row3.pack(fill="x", padx=14, pady=(2, 10))
        ctk.CTkLabel(row3, text="卡片透明度", font=(FONT, 15), text_color=TEXT).pack(side="left")
        ctk.CTkLabel(row3, text="卡片 / 侧边栏 / 按钮统一用这个（0%=全透明）",
                     font=(FONT, 12), text_color=DIM).pack(side="left", padx=(10, 0))
        _op = int(round(float(self.settings.get("panel_opacity", 0.5)) * 100))
        self.opacity_label = ctk.CTkLabel(row3, text=f"{_op}%", font=(FONT, 13),
                                          text_color=ACCENT, width=44)
        self.opacity_label.pack(side="right")
        self.opacity_slider = ctk.CTkSlider(
            row3, from_=0, to=100, number_of_steps=20, width=150, height=16,
            fg_color=BTN, progress_color=ACCENT, button_color=ACCENT,
            button_hover_color=ACCENT_DARK, command=self._on_panel_opacity_change)
        self.opacity_slider.set(_op)
        self.opacity_slider.pack(side="right", padx=(10, 4))

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

    def _build_obs_body(self, parent):
        """「连接 OBS」展开后：开关 + 地址 + 复制"""
        ctk.CTkLabel(parent, text="在 OBS 里添加「浏览器源」，粘贴下面的地址即可在直播画面上显示收益。",
                     font=(FONT, 12), text_color=DIM, justify="left").pack(anchor="w", padx=14, pady=(0, 6))
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(0, 10))
        self.obs_var = ctk.BooleanVar(value=bool(self.settings.get("obs_browser_source", False)))
        ctk.CTkSwitch(row, text="开启", variable=self.obs_var, onvalue=True, offvalue=False,
                      font=(FONT, 14), fg_color=SWITCH_OFF, progress_color=ACCENT, text_color=TEXT,
                      command=self._toggle_obs_source).pack(side="left")
        api_port = int(self.settings.get("api_port", 8765))
        self._obs_addr_label = ctk.CTkLabel(row, text=f"http://127.0.0.1:{api_port}/overlay",
                                            font=(FONT, 13), text_color=TEXT)
        self._obs_addr_label.pack(side="left", padx=(16, 8))
        ctk.CTkButton(row, text="复制", font=(FONT, 13), width=56, height=28,
                      corner_radius=8, fg_color=BTN, hover_color=BTN_HOVER,
                      command=self._copy_obs_addr).pack(side="left")


    @staticmethod
    def _rollover_text(h):
        h = int(h) % 24
        if h == 0:
            return "0 点"
        if h < 6:
            return f"凌晨 {h} 点"
        if h < 12:
            return f"上午 {h} 点"
        return f"{h} 点"

    def _on_rollover_change(self, value):
        try:
            h = int(round(float(value))) % 24
            self.rollover_var.set(str(h))
            self.rollover_label.configure(text=self._rollover_text(h))
        except Exception:
            pass
        # 拖动过程中不频繁写文件，停 0.4 秒后再保存生效
        try:
            if getattr(self, "_ro_after", None):
                try:
                    self.after_cancel(self._ro_after)
                except Exception:
                    pass
            self._ro_after = self.after(400, self._on_any_setting_change)
        except Exception:
            pass

    # ---------- 全局热键：按键捕获 ----------

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

    def _make_setting_card(self, parent, icon, title, desc, wide=False):
        """设置项卡片：和启动页同款横向长条

        [图标小卡] [标题 + 说明] …… [右侧控件区]
        返回右侧（或下方）的控件容器，调用方把控件 pack 进去。
        """
        card = ctk.CTkFrame(parent, corner_radius=RADIUS_CARD, fg_color=CARD,
                            border_width=1, border_color=theme.BORDER)
        card.pack(fill="x", pady=(0, 8))
        holder = ctk.CTkFrame(card, fg_color="transparent")
        ic = ctk.CTkFrame(card, width=42, height=42, corner_radius=12, fg_color=CARD_INNER)
        mid = ctk.CTkFrame(card, fg_color="transparent")
        if wide:
            holder.pack(fill="x", padx=14, pady=(0, 10))
        else:
            # 固定宽度 + 不许子控件撑大：这样每张卡片右边的控件都能对齐
            # 宽度调窄一些（原来 300 太宽），输入框/下拉看起来更紧凑
            holder.configure(width=178, height=44)
            holder.pack_propagate(False)
            holder.pack(side="right", padx=(10, 14), pady=9)
        ic.pack(side="left", padx=(14, 12), pady=9)
        ic.pack_propagate(False)
        ctk.CTkLabel(ic, text=icon, font=(FONT, 20), text_color=ACCENT).place(
            relx=0.5, rely=0.5, anchor="center")
        mid.pack(side="left", fill="both", expand=True, pady=9)
        ctk.CTkLabel(mid, text=title, font=(FONT, 16, "bold"), text_color=TEXT,
                     anchor="w").pack(anchor="w")
        ctk.CTkLabel(mid, text=desc, font=(FONT, 12), text_color=DIM, anchor="w",
                     justify="left", wraplength=300).pack(anchor="w", pady=(2, 0))
        return holder

    def _on_settings_tab(self, name):
        """切换设置页标签：同一格里只显示当前标签的滚动容器"""
        try:
            for k, f in getattr(self, "_settings_tabs", {}).items():
                if k == name:
                    f.grid()
                    try:
                        f._parent_canvas.yview_moveto(0)
                    except Exception:
                        pass
                else:
                    f.grid_remove()
        except Exception:
            pass

    def _setting_row(self, card, title, desc):
        ctk.CTkLabel(card, text=title, font=(FONT, 16), text_color=TEXT).pack(padx=20, pady=(6, 0), anchor="w")
        ctk.CTkLabel(card, text=desc, font=(FONT, 13), text_color=DIM).pack(padx=20, pady=(0, 4), anchor="w")

    # ---------- 开发者选项（AI 样本采集）----------

    def _build_dev_card(self, scroll, r):
        """构建开发者选项卡片（仅开发者模式显示）"""
        card = self._make_card(scroll)
        card.grid(row=r, column=0, sticky="ew", pady=(0, 10))
        ctk.CTkLabel(card, text="🛠 开发者选项", font=(FONT, 16, "bold"), text_color=ACCENT).pack(padx=20, pady=(12, 4))
        ctk.CTkLabel(
            card, text="本地 AI 样本采集（仅供开发者收集训练数据，不影响普通使用）。\n"
                       "截图全部保存在本地，不上传、不联网、不进 Git。",
            font=(FONT, 12), text_color=DIM, justify="left",
        ).pack(anchor="w", padx=20, pady=(0, 8))

        # 启用样本采集
        self.dataset_enabled_var = ctk.BooleanVar(value=bool(self.settings.get("dataset_enabled", False)))
        ctk.CTkSwitch(
            card, text="启用样本采集", variable=self.dataset_enabled_var, onvalue=True, offvalue=False,
            font=(FONT, 15), fg_color=SWITCH_OFF, progress_color=ACCENT, text_color=TEXT,
        ).pack(anchor="w", padx=20, pady=(0, 6))

        # 保存位置
        self._setting_row(card, "保存位置", "样本保存目录（默认在用户目录，不在项目内）")
        path_row = ctk.CTkFrame(card, fg_color="transparent")
        path_row.pack(fill="x", padx=20, pady=(0, 4))
        self._dataset_path_label = ctk.CTkLabel(
            path_row, text=self._dev_path_display(), font=(FONT, 12), text_color=TEXT, anchor="w",
        )
        self._dataset_path_label.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            path_row, text="浏览…", font=(FONT, 13), width=60, height=26,
            corner_radius=8, fg_color=BTN, hover_color=BTN_HOVER, command=self._on_choose_dataset_path,
        ).pack(side="right")

        # 统计
        self._dev_stats_label = ctk.CTkLabel(card, text="", font=(FONT, 12), text_color=DIM, justify="left")
        self._dev_stats_label.pack(anchor="w", padx=20, pady=(4, 6))
        self._refresh_dev_stats()

        # 手动采集 + 操作按钮
        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.pack(fill="x", padx=20, pady=(0, 6))
        ctk.CTkButton(
            btns, text="采集 GAMEPLAY", font=(FONT, 13), height=28, corner_radius=8,
            fg_color=BTN, hover_color=BTN_HOVER, command=lambda: self._on_manual_capture("gameplay"),
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            btns, text="采集 NON_GAMEPLAY", font=(FONT, 13), height=28, corner_radius=8,
            fg_color=BTN, hover_color=BTN_HOVER, command=lambda: self._on_manual_capture("non_gameplay"),
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            btns, text="打开文件夹", font=(FONT, 13), height=28, corner_radius=8,
            fg_color=BTN, hover_color=BTN_HOVER, command=self._on_open_dataset,
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            btns, text="清空样本", font=(FONT, 13), height=28, corner_radius=8,
            fg_color=DANGER, hover_color=DANGER_HOVER, command=self._on_clear_dataset,
        ).pack(side="left")

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

    # ---------- 外观设置 ----------

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
                       bool(self.settings.get("sidebar_glass", True)))
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

    def on_save_settings(self):
        """兼容旧逻辑：手动保存一次（现在设置本来就是即时生效的）"""
        try:
            self._on_any_setting_change()
        except Exception:
            pass

    # ---- 通用卡片 ----

    def _make_card(self, parent):
        return ctk.CTkFrame(parent, corner_radius=RADIUS_CARD, fg_color=CARD,
                            border_width=1, border_color=theme.BORDER)

    # ================= 页面切换 =================

    @staticmethod
    def _grid_page(frame, show):
        """显示 / 隐藏一个页面（页面自己不再 grid，统一在这里控制）"""
        try:
            if frame is None:
                return
            if show:
                frame.grid(row=0, column=0, sticky="nsew", padx=22, pady=18)
            else:
                frame.grid_remove()
        except Exception:
            pass

    def _ensure_page(self, key):
        """按需构建页面（懒加载）：第一次切到某页才建它"""
        if key in getattr(self, "_pages", {}):
            return self._pages[key]
        frame = None
        try:
            frame = self._page_builders[key]()
        except Exception:
            frame = None
        self._pages[key] = frame
        # 只有「当前页」才显示；后台预建出来的其它页完全不 grid，
        # 这样启动时就不会闪一下设置界面了
        self._grid_page(frame, key == getattr(self, "_current_page", None))
        return frame

    def _show_page(self, key):
        self._current_page = key
        self._ensure_page(key)
        for k, f in getattr(self, "_pages", {}).items():
            self._grid_page(f, k == key)
        # 页面刚显示出来才有真实尺寸，这时候补贴一次背景图切片
        if self.settings.get("bg_image"):
            self._apply_background()
        for k, btn in self.nav_btns.items():
            if k == key:
                btn.configure(fg_color=NAV_ON, text_color=ACCENT, font=(FONT, 16, "bold"))
            else:
                btn.configure(fg_color="transparent", text_color=DIM, font=(FONT, 16))
        # 进「收益记录」时刷新一次列表
        if key == "records":
            try:
                self._rebuild_records()
            except Exception:
                pass
        # 刚建好的页面补一次数据刷新
        try:
            self._refresh_ui()
        except Exception:
            pass

    # ================= 主循环 =================

    def _tick_loop(self):
        try:
            # 1. 取检测线程的消息（识别在后台线程跑，这里只收结果，界面不卡）
            try:
                while True:
                    kind, payload = self._detect_queue.get_nowait()
                    if kind == "event":
                        ts, desc = payload
                        self.last_event_label.configure(
                            text=f"🕐 最后识别：{desc}  ({time.strftime('%H:%M:%S', time.localtime(ts))})"
                        )
                    elif kind == "error":
                        self.stop_monitor()
                        self._set_status("监测出错已停止", BAD)
            except queue.Empty:
                pass

            # 2. 托盘动作
            for action in self.tray.poll():
                if action == "show":
                    self.show_main()
                elif action == "start":
                    if not self.monitoring:
                        self.start_monitor()
                elif action == "stop":
                    if self.monitoring:
                        self.stop_monitor()
                elif action == "open_data":
                    self._open_data_dir()
                elif action == "exit":
                    self.on_exit()

            # 3. 刷新界面（内部只在数据变化时重建列表）
            self._refresh_ui()

            # 4. 开发者选项：把后台算好的样本统计显示出来（不阻塞）
            self._apply_dev_stats()

            # 5. 跨过「换日时间」就自动换日（挂过零点也不会一直算同一天）
            try:
                if self.stats.check_day():
                    self._prev_list_sig = None
                    self._refresh_ui()
                    if "records" in getattr(self, "_pages", {}):
                        self._rebuild_records()
            except Exception:
                pass
        except Exception:
            pass
        # 界面刷新频率固定 200ms（检测频率由后台线程控制）
        self.after(200, self._tick_loop)

    # ================= 监测控制 =================

    def on_start_stop(self):
        if self.monitoring:
            self.stop_monitor()
        else:
            self.start_monitor()

    def _prewarm_ocr(self):
        """主线程预热 OCR 模型（避免后台线程首次加载 onnxruntime 的潜在问题）"""
        try:
            from ocr_engine import OcrEngine
            ocr = OcrEngine()
            ocr._ensure()
            import numpy as np
            ocr.recognize_line(np.zeros((40, 400, 3), dtype=np.uint8))
        except Exception:
            pass

    def start_monitor(self):
        # 预热 OCR 模型（主线程加载，1~3秒；避免后台线程首次加载闪退）
        self._set_status("正在加载识别模型…", DIM)
        self.update_idletasks()
        self._prewarm_ocr()
        # 优先用【自动扫全屏游戏窗口】：材料/圣遗物拾取提示出现在哪都能识别，
        # 摩拉位置也不用手动指定。找不到游戏窗口时才退回手动框选区域。
        from capture import find_game_window
        win = find_game_window()
        region = None
        mode_text = "正在监测（自动识别游戏窗口）"
        if win is None:
            # 没有游戏窗口 → 用之前框选的手动区域（若有）
            region = self.settings.get("region")
            if not region:
                messagebox.showinfo("提示", "没有找到原神游戏窗口。\n\n请先打开游戏（用无边框窗口模式），再点开始监测。")
                return
            mode_text = "正在监测"
        # 启动后台检测线程（OCR 很慢，必须在后台跑，否则界面卡死）
        self._detect_stop = threading.Event()
        self._detect_queue = queue.Queue()
        self._detect_err_streak = 0
        self._detect_thread = threading.Thread(
            target=self._detect_loop, args=(region,), daemon=True
        )
        self._detect_thread.start()
        self.monitoring = True
        self._monitor_start = time.monotonic()
        # 收益记录：记下开始时的数据快照，停止时算差值写一条记录
        self._sess_start_ts = time.time()
        self._sess_snapshot = (
            self.stats.mora,
            self.stats.artifact,
            dict(self.stats.materials),
            dict(self.stats.normal_materials),
        )
        self._set_status(mode_text, GOOD)
        self._set_start_ui(True)

    def _detect_loop(self, region):
        """后台检测线程：识别（含慢速OCR）全部在这里跑，主线程只管界面"""
        stop_ev = self._detect_stop  # 局部引用，避免主线程置 None 后竞态
        try:
            det = Detector(region, ICONS_DIR, self.settings, stats=self.stats)
        except Exception as e:
            try:
                self._detect_queue.put(("error", str(e)))
            except Exception:
                pass
            return
        self.detector = det
        try:
            last_ts = None
            while stop_ev is not None and not stop_ev.is_set():
                try:
                    det.tick()
                    self._detect_err_streak = 0
                except Exception:
                    # 连续出错才上报停止（偶尔一次不影响）
                    self._detect_err_streak += 1
                    if self._detect_err_streak > 20:
                        try:
                            self._detect_queue.put(("error", "连续识别失败"))
                        except Exception:
                            pass
                        break
                # 识别到新事件 → 报给主线程显示
                ev = det.last_event
                if ev is not None and ev[0] != last_ts:
                    last_ts = ev[0]
                    try:
                        self._detect_queue.put(("event", ev))
                    except Exception:
                        pass
                interval = max(0.02, int(self.settings.get("tick_interval", 50)) / 1000.0)
                stop_ev.wait(interval)
        finally:
            try:
                det.close()
            except Exception:
                pass
            self.detector = None

    def stop_monitor(self):
        if self.monitoring and self._monitor_start:
            self.stats.running_seconds += int(time.monotonic() - self._monitor_start)
            self.stats.save()
        self._record_session()   # 写入「收益记录」
        self.monitoring = False
        self._monitor_start = None
        # 停止后台检测线程（daemon，不 join 避免卡界面；detector 在线程内已 close）
        if self._detect_stop is not None:
            try:
                self._detect_stop.set()
            except Exception:
                pass
        self._detect_stop = None
        self._detect_thread = None
        self._set_status("已暂停", BAD)
        self._set_start_ui(False)

    def _record_session(self):
        """把这次监测的收益差值写进「收益记录」"""
        try:
            snap = getattr(self, "_sess_snapshot", None)
            start_ts = getattr(self, "_sess_start_ts", None)
            if snap is None or start_ts is None:
                return
            self._sess_snapshot = None
            self._sess_start_ts = None
            s_mora, s_art, s_mat, s_norm = snap
            # 当前材料（怪物 + 普通合并）
            cur = dict(self.stats.materials)
            for k, v in self.stats.normal_materials.items():
                cur[k] = cur.get(k, 0) + v
            old = dict(s_mat)
            for k, v in s_norm.items():
                old[k] = old.get(k, 0) + v
            gained = {}
            for k, v in cur.items():
                d = int(v) - int(old.get(k, 0))
                if d > 0:
                    gained[k] = d
            now = time.time()
            rec = sessions.make_record(
                start_ts, now, now - start_ts,
                self.stats.mora - s_mora,
                self.stats.artifact - s_art,
                gained,
            )
            sessions.add_session(rec)
            try:
                self._rebuild_records()
            except Exception:
                pass
        except Exception:
            pass

    def on_reselect(self):
        """重新框选识别区域（不隐藏主窗口，遮罩本身在最顶层）"""
        was_monitoring = self.monitoring
        if was_monitoring:
            self.stop_monitor()
        try:
            region = region_selector.select_region(self)
        except Exception as e:
            messagebox.showerror(
                "框选失败",
                f"框选出现错误：{e}\n\n请再试一次。\n提示：如果看不到框选界面，可能是游戏全屏独占，"
                "请按 Esc 取消，把游戏改成无边框窗口模式。",
            )
            return
        if region:
            self.settings["region"] = region
            config_manager.save_settings(self.settings)
            if self.detector:
                self.detector.region = region  # 检测器直接用新区域
            messagebox.showinfo("成功", "识别区域已更新")
        self._refresh_region_state()

    def on_settings(self):
        IconManagerWindow(self, on_change=self.reload_icons)

    def on_check_update(self):
        """检测 GitHub Releases 是否有新版本（后台线程，不卡界面）"""
        self.update_status_label.configure(text="正在检测…", text_color=DIM)
        import threading

        def _do():
            try:
                import urllib.request
                import json
                req = urllib.request.Request(
                    "https://api.github.com/repos/Cash-553/genshin-income-tracker/releases/latest",
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                latest = str(data.get("tag_name", "")).lstrip("v")
                current = "0.7"
                if latest and latest != current:
                    url = data.get("html_url", "https://github.com/Cash-553/StatGI/releases")
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

    # ================= 界面刷新 =================

    def _set_start_ui(self, running):
        """开始/停止监测时，同步更新启动页那张卡片（标题 + 按钮）"""
        try:
            self.start_card_title.configure(text="停止监测" if running else "开始监测")
            self.start_card_btn.configure(text="停止" if running else "开始")
        except Exception:
            pass

    def _refresh_region_state(self):
        r = self.settings.get("region")
        if not r:
            # 自动模式：不用框选，程序自动找游戏窗口
            self._set_status("未框选（自动检测游戏窗口）", DIM)
            self._set_start_ui(False)
            try:
                self.launch_region_label.configure(text="自动检测游戏窗口（也可「重新框选」手动指定）")
            except Exception:
                pass
        else:
            self._set_start_ui(False)
            try:
                self.launch_region_label.configure(text=f"({r['x']}, {r['y']})  {r['w']}×{r['h']}")
            except Exception:
                pass

    def _set_status(self, text, color=None):
        color = color or TEXT
        dot = {"#4A90D9": "●", "#9E9E9E": "●", "#F2F2F2": "●"}.get(color, "●")
        self.status_label.configure(text=f"{dot} {text}", text_color=color)
        try:
            self.launch_status_label.configure(text=f"{dot} {text}", text_color=color)
        except Exception:
            pass

    def _refresh_ui(self):
        # 「今日统计」页还没建（懒加载）时跳过，建好后 _show_page 会再刷一次
        if "home" not in getattr(self, "_pages", {}):
            return
        try:
            # 只在数值真的变了才 configure（每次 configure 都会触发控件重绘）
            _mora = f"{self.stats.mora:,}"
            if getattr(self, "_ui_mora_txt", None) != _mora:
                self._ui_mora_txt = _mora
                self.mora_label.configure(text=_mora)

            total = self.stats.running_seconds
            if self.monitoring and self._monitor_start:
                total += int(time.monotonic() - self._monitor_start)
            _t = fmt_time(total)
            if getattr(self, "_ui_time_txt", None) != _t:
                self._ui_time_txt = _t
                self.time_label.configure(text=_t)

            _art = f"×{self.stats.artifact}"
            if getattr(self, "_ui_art_txt", None) != _art:
                self._ui_art_txt = _art
                self.artifact_label.configure(text=_art)

            # 素材列表（合并材料，只在数据变化时重建）
            merged = dict(self.stats.materials)
            for k, v in self.stats.normal_materials.items():
                merged[k] = merged.get(k, 0) + v
            sig = (self.stats.mora, self.stats.artifact, tuple(sorted(merged.items())))
            if sig != self._prev_list_sig:
                self._prev_list_sig = sig
                self._rebuild_mat_list(merged)
                self._rebuild_detail_list()
        except Exception:
            pass

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
            return
        for name, count in items:
            row = ctk.CTkFrame(self.mat_scroll, fg_color="transparent")
            row.pack(fill="x", padx=6, pady=2)
            ctk.CTkLabel(row, text=name, font=(FONT, 16), text_color=TEXT).pack(side="left")
            ctk.CTkLabel(row, text=f"×{count}", font=(FONT, 16, "bold"), text_color=ACCENT).pack(side="right")

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

    # ================= 数据接口 =================

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

    # ================= 窗口控制 =================

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
            self._uninstall_wndproc()
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


if __name__ == "__main__":
    # 防止重复打开（两个程序同时识别会重复统计）
    import ctypes
    import sys
    _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "GenshinIncomeTracker_SingleInstance")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        messagebox.showwarning("提示", "程序已经在运行了。\n请到右下角托盘找到它。")
        root.destroy()
        sys.exit(0)

    app = MainApp()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
