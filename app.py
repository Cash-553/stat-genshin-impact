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
import materials_db
import paths
import region_selector
import theme
from detector import Detector
from stats import DailyStats
from icon_manager import IconManagerWindow
from tray import Tray
from api_server import ApiServer

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


class MainApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("StatGI")
        self.overrideredirect(True)   # 无边框窗口（插件风格）
        # 初始大小与 BetterGI 源码一致（900×600），窗口居中
        try:
            import ctypes
            hdc = ctypes.windll.user32.GetDC(0)
            dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
            ctypes.windll.user32.ReleaseDC(0, hdc)
            scale = (dpi if dpi > 0 else 96) / 96.0
        except Exception:
            scale = 1.0
        self.geometry(f"{int(900 / scale)}x{int(600 / scale)}")
        self.resizable(False, False)  # 无边框窗口用自定义边缘拖拽调大小
        # 居中显示（与 BetterGI CenterScreen 一致）
        self.update_idletasks()
        try:
            sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
            w, h = self.winfo_width(), self.winfo_height()
            x = max(0, (sw - w) // 2)
            y = max(0, (sh - h) // 2)
            self.geometry(f"+{int(x / scale)}+{int(y / scale)}")
        except Exception:
            pass
        # 无边框窗口也显示在任务栏（图标 + 按钮）
        self._set_window_icon()
        self._enable_taskbar()
        # 窗口每次显示（含从托盘恢复）都重新确保任务栏按钮；启动后再补几次，防时机问题
        self.bind("<Map>", lambda e: (self.after(100, self._enable_taskbar), self.after(100, self._install_wndproc)))
        self.after(300, lambda: (self._enable_taskbar(), self._install_wndproc()))
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
        self.stats = DailyStats()
        self.detector = None          # 开始监测时才创建
        self.monitoring = False
        self.demo_active = False      # 演示模式开关
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


    def _install_wndproc(self):
        """子类化窗口过程：拦截任务栏按钮的「还原/最小化」系统消息。

        无边框窗口没有标准标题栏，任务栏按钮点击后系统发的
        SC_RESTORE / SC_MINIMIZE 消息 Tk 不会处理，导致窗口呼不出来。
        这里拦截后转成我们自己 show_main / 最小化到托盘。
        需要窗口句柄创建好之后调用；已安装过就跳过（幂等）。
        """
        if getattr(self, "_orig_wndproc", 0):
            return  # 已经装过
        try:
            import ctypes
            user32 = ctypes.windll.user32
            # 64位系统：参数必须显式声明类型，否则指针会被截断成32位导致失败
            user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
            user32.SetWindowLongPtrW.restype = ctypes.c_void_p
            user32.CallWindowProcW.argtypes = [
                ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_longlong,
            ]
            user32.CallWindowProcW.restype = ctypes.c_longlong
            WM_SYSCOMMAND = 0x0112
            WM_ACTIVATE = 0x0006
            WA_ACTIVE = 1
            SC_RESTORE = 0xF120
            SC_MINIMIZE = 0xF020
            GWLP_WNDPROC = -4

            hwnd = int(self.winfo_id())
            if hwnd == 0:
                return

            WNDPROC = ctypes.WINFUNCTYPE(
                ctypes.c_longlong,   # LRESULT
                ctypes.c_void_p,     # HWND
                ctypes.c_uint,       # UINT
                ctypes.c_size_t,     # WPARAM
                ctypes.c_longlong,   # LPARAM
            )

            def _proc(hwnd_, msg, wparam, lparam):
                # 重要：ctypes 窗口回调绝不能抛异常！
                # 一旦异常，进程会直接 fail-fast 闪退（0xc0000409）。
                # 所以这里所有操作都要 try 包住，异常时只转发给原过程。
                try:
                    if msg == WM_SYSCOMMAND:
                        cmd = wparam & 0xFFF0
                        if cmd == SC_RESTORE:
                            # 点击任务栏按钮还原 → 只在确实最小化过时才呼出
                            if getattr(self, "_minimized", False):
                                try:
                                    self.after(0, self.show_main)
                                except Exception:
                                    pass
                            return 0
                        if cmd == SC_MINIMIZE:
                            try:
                                self.after(0, self._minimize_to_tray)
                            except Exception:
                                pass
                            return 0
                    if msg == WM_ACTIVATE and (wparam & 0xFFFF) == WA_ACTIVE:
                        # 窗口被激活：只在"最小化（屏幕外）"状态下才恢复位置。
                        # 注意：不能无条件呼出！否则 激活→呼出→抢焦点→再激活 会死循环，
                        # 导致界面卡死（未响应）并最终 fail-fast 闪退。
                        if getattr(self, "_minimized", False):
                            try:
                                self.after(0, self.show_main)
                            except Exception:
                                pass
                except Exception:
                    pass
                # 其它消息交给原窗口过程（Tk 正常处理）
                try:
                    return user32.CallWindowProcW(self._orig_wndproc, hwnd_, msg, wparam, lparam)
                except Exception:
                    return 0

            cb = WNDPROC(_proc)
            self._wndproc_cb = cb  # 必须保持引用，防止被回收导致崩溃
            old = user32.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, ctypes.cast(cb, ctypes.c_void_p))
            if not old:
                return
            self._orig_wndproc = old
        except Exception:
            pass

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

    def _enable_taskbar(self):
        """让无边框窗口在任务栏显示按钮（WS_EX_APPWINDOW + ITaskbarList::AddTab）。

        需要在窗口真正显示（Map）后再调用才有效，所以：
        - 启动后延时调用
        - 绑定 <Map> 事件：窗口每次显示（含从托盘恢复）都重新确保
        """
        try:
            import ctypes
            hwnd = int(self.winfo_id())
            if hwnd == 0:
                return  # 窗口句柄还没创建好，等下次再试
            GWL_EXSTYLE = -20
            WS_EX_APPWINDOW = 0x00040000
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_APPWINDOW)
            SWP_FRAMECHANGED = 0x0020
            ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, SWP_FRAMECHANGED | 0x0001 | 0x0002)
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
                AddTab(p, c_void_p(int(self.winfo_id())))
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
                                 font=(FONT, 15, "bold"), text_color=TEXT)
        title_lbl.pack(side="left", padx=16)

        self.status_label = ctk.CTkLabel(header, text="未开始",
                                         font=(FONT, 12, "bold"), text_color=BAD)
        self.status_label.pack(side="left", padx=14)

        close_btn = ctk.CTkButton(
            header, text="✕", width=36, height=26, corner_radius=RADIUS_BTN, font=(FONT, 13),
            fg_color="transparent", hover_color="#3A2A2A", text_color=TEXT, command=self.on_close,
        )
        close_btn.pack(side="right", padx=(0, 10), pady=9)
        min_btn = ctk.CTkButton(
            header, text="─", width=36, height=26, corner_radius=RADIUS_BTN, font=(FONT, 13),
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

        # Logo 区
        logo = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        logo.pack(fill="x", pady=(16, 2))
        ctk.CTkLabel(logo, text="🍃", font=(FONT, 26)).pack()
        ctk.CTkLabel(logo, text="原神收益统计器", font=(FONT, 12, "bold"), text_color=TEXT).pack()
        ctk.CTkLabel(logo, text="StatGI", font=(FONT, 9), text_color=DIM).pack(pady=(0, 4))

        self.sidebar_date = ctk.CTkLabel(
            self.sidebar, text=self.stats.date, font=(FONT, 11), text_color=DIM,
        )
        self.sidebar_date.pack(pady=(6, 10))

        self.nav_btns = {}
        for key, icon, label in [
            ("launch", "🚀", "启动"),
            ("home", "📊", "今日统计"),
            ("materials", "⚔", "素材明细"),
            ("bar", "📶", "收益统计条"),
            ("settings", "⚙", "设置"),
        ]:
            btn = ctk.CTkButton(
                self.sidebar, text=f"{icon}  {label}",
                font=(FONT, 13),
                height=40, corner_radius=RADIUS_BTN,
                fg_color="transparent", hover_color=NAV_ON,
                text_color=DIM, anchor="w",
                command=lambda k=key: self._show_page(k),
            )
            btn.pack(fill="x", padx=10, pady=2)
            self.nav_btns[key] = btn

        ctk.CTkLabel(self.sidebar, text="V0.4", font=(FONT, 10), text_color=DIM).pack(side="bottom", pady=12)

        # 右侧内容区（透明）
        self.content = ctk.CTkFrame(body, corner_radius=0, fg_color="transparent")
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self._build_page_launch()
        self._build_page_home()
        self._build_page_materials()
        self._build_page_bar()
        self._build_page_settings()

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

    # ---------- 自定义背景（图片铺底 + 毛玻璃侧边栏）----------

    def _on_resize(self, event):
        """窗口尺寸变化时（去抖）重新生成背景，避免频繁重绘"""
        if getattr(self, "_resize_after", None):
            try:
                self.after_cancel(self._resize_after)
            except Exception:
                pass
        self._resize_after = self.after(150, self._apply_background)

    def _apply_background(self):
        """根据设置应用背景：自定义图片铺底（可选毛玻璃侧边栏），无图用纯色"""
        for w in getattr(self, "_bg_layers", []):
            try:
                w.destroy()
            except Exception:
                pass
        self._bg_layers = []

        img_path = self.settings.get("bg_image")
        has_img = bool(img_path) and Path(img_path).exists()
        glass = bool(self.settings.get("sidebar_glass", True)) and has_img

        # 侧边栏：毛玻璃时透明（由图片层模拟磨砂），否则默认色
        try:
            self.sidebar.configure(fg_color="transparent" if glass else SIDEBAR)
        except Exception:
            pass

        if not has_img:
            return
        try:
            from PIL import Image, ImageTk
            img = Image.open(img_path).convert("RGB")
            w = max(100, self.winfo_width())
            h = max(100, self.winfo_height())
            # cover 缩放：铺满窗口并居中裁剪
            scale = max(w / img.width, h / img.height)
            img = img.resize(
                (max(1, int(img.width * scale)), max(1, int(img.height * scale))),
                Image.LANCZOS,
            )
            x = (img.width - w) // 2
            y = (img.height - h) // 2
            img = img.crop((x, y, x + w, y + h))

            # 背景层（垫在所有控件下面）
            photo = ImageTk.PhotoImage(img)
            self._bg_photo = photo
            lbl = tk.Label(self, image=photo, bd=0, highlightthickness=0)
            lbl.place(x=0, y=0, relwidth=1, relheight=1)
            lbl.lower()
            self._bg_layers.append(lbl)

            # 毛玻璃侧边栏：背景图模糊 + 压暗，模拟磨砂效果
            if glass:
                self._apply_sidebar_glass(img)
        except Exception:
            pass

    def _apply_sidebar_glass(self, bg_img):
        """左侧栏毛玻璃：取背景图左半部分，模糊+压暗后铺在侧边栏底部"""
        try:
            from PIL import Image, ImageTk, ImageFilter
            sw = 180
            sh = max(100, self.winfo_height())
            crop = bg_img.crop((0, 0, min(sw, bg_img.width), min(sh, bg_img.height)))
            crop = crop.resize((sw, sh), Image.LANCZOS)
            crop = crop.filter(ImageFilter.GaussianBlur(14))
            overlay = Image.new("RGB", crop.size, (12, 12, 14))
            crop = Image.blend(crop, overlay, 0.55)  # 压暗，保证文字可读
            photo = ImageTk.PhotoImage(crop)
            self._sb_photo = photo
            lbl = tk.Label(self.sidebar, image=photo, bd=0, highlightthickness=0)
            lbl.place(x=0, y=0, relwidth=1, relheight=1)
            lbl.lower()
            self._bg_layers.append(lbl)
        except Exception:
            pass

    # ---- 页面：启动（默认首页）----

    def _build_page_launch(self):
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        page.grid(row=0, column=0, sticky="nsew", padx=22, pady=18)
        page.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(page, text="启动", font=(FONT, 20, "bold"), text_color=ACCENT).grid(
            row=0, column=0, sticky="w", pady=(0, 12))

        # 状态卡片
        status_card = self._make_card(page)
        status_card.grid(row=1, column=0, sticky="ew")
        head = ctk.CTkFrame(status_card, fg_color="transparent")
        head.pack(fill="x", padx=20, pady=(12, 2))
        ctk.CTkLabel(head, text="监测状态", font=(FONT, 12, "bold"), text_color=ACCENT).pack(side="left")
        row1 = ctk.CTkFrame(status_card, fg_color="transparent")
        row1.pack(fill="x", padx=20, pady=(4, 2))
        ctk.CTkLabel(row1, text="🟢 状态：", font=(FONT, 13), text_color=DIM).pack(side="left")
        self.launch_status_label = ctk.CTkLabel(row1, text="未开始", font=(FONT, 13, "bold"), text_color=BAD)
        self.launch_status_label.pack(side="left")
        row2 = ctk.CTkFrame(status_card, fg_color="transparent")
        row2.pack(fill="x", padx=20, pady=2)
        ctk.CTkLabel(row2, text="📍 识别区域：", font=(FONT, 13), text_color=DIM).pack(side="left")
        self.launch_region_label = ctk.CTkLabel(row2, text="未设置", font=(FONT, 13), text_color=TEXT)
        self.launch_region_label.pack(side="left")
        row3 = ctk.CTkFrame(status_card, fg_color="transparent")
        row3.pack(fill="x", padx=20, pady=(2, 12))
        ctk.CTkLabel(row3, text="🕐 最后识别：", font=(FONT, 13), text_color=DIM).pack(side="left")
        self.last_event_label = ctk.CTkLabel(row3, text="—", font=(FONT, 13), text_color=TEXT)
        self.last_event_label.pack(side="left")

        # 主按钮（开始监测）
        main_btns = ctk.CTkFrame(page, fg_color="transparent")
        main_btns.grid(row=2, column=0, sticky="ew", pady=(14, 6))
        main_btns.grid_columnconfigure(0, weight=1)
        self.start_btn = ctk.CTkButton(
            main_btns, text="▶ 开始监测", font=(FONT, 18),
            height=54, corner_radius=RADIUS_BTN, fg_color=ACCENT, hover_color=ACCENT_DARK,
            text_color="#FFFFFF", command=self.on_start_stop,
        )
        self.start_btn.grid(row=0, column=0, sticky="ew")

        # 次要按钮
        sub_btns = ctk.CTkFrame(page, fg_color="transparent")
        sub_btns.grid(row=3, column=0, sticky="ew", pady=(0, 6))
        for i in range(5):
            sub_btns.grid_columnconfigure(i, weight=1)
        ctk.CTkButton(
            sub_btns, text="重新框选", font=(FONT, 13),
            height=40, corner_radius=8, fg_color=BTN, hover_color=BTN_HOVER,
            command=self.on_reselect,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 5))
        self.demo_btn = ctk.CTkButton(
            sub_btns, text="🎬 演示模式", font=(FONT, 12),
            height=40, corner_radius=8, fg_color=BTN, hover_color=BTN_HOVER,
            command=self.on_demo,
        )
        self.demo_btn.grid(row=0, column=1, sticky="ew", padx=5)
        ctk.CTkButton(
            sub_btns, text="清空今日", font=(FONT, 13),
            height=40, corner_radius=8, fg_color=DANGER, hover_color=DANGER_HOVER,
            command=self.on_clear_today,
        ).grid(row=0, column=2, sticky="ew", padx=5)
        ctk.CTkButton(
            sub_btns, text="清空时间", font=(FONT, 13),
            height=40, corner_radius=8, fg_color=DANGER, hover_color=DANGER_HOVER,
            command=self.on_clear_runtime,
        ).grid(row=0, column=3, sticky="ew", padx=5)
        ctk.CTkButton(
            sub_btns, text="📷 诊断截图", font=(FONT, 12),
            height=40, corner_radius=8, fg_color=BTN, hover_color=BTN_HOVER,
            command=self.on_debug_screenshot,
        ).grid(row=0, column=4, sticky="ew", padx=(5, 0))

        # 使用流程卡片
        guide = self._make_card(page)
        guide.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        ctk.CTkLabel(guide, text="使用流程", font=(FONT, 13, "bold"), text_color=ACCENT).pack(padx=20, pady=(12, 4))
        ctk.CTkLabel(
            guide,
            text="1️⃣ 打开原神（建议无边框窗口模式）\n"
                 "2️⃣ 点「开始监测」——程序自动找到游戏窗口并识别\n"
                 "   （不用手动框选，掉落提示出现在哪里都能识别）\n"
                 "3️⃣ 在「今日统计」查看收益，或打开「收益统计条」放直播间\n"
                 "4️⃣ 想只识别某一小块区域？点「重新框选」手动指定",
            font=(FONT, 12), text_color=DIM, justify="left",
        ).pack(padx=20, pady=(0, 14))

    # ---- 页面：今日统计 ----

    def _build_page_home(self):
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        page.grid(row=0, column=0, sticky="nsew", padx=22, pady=18)
        page.grid_columnconfigure(0, weight=1)

        # 上排三个卡片：摩拉 / 狗粮 / 挂机时间
        cards = ctk.CTkFrame(page, fg_color="transparent")
        cards.grid(row=0, column=0, sticky="ew")
        for i in range(3):
            cards.grid_columnconfigure(i, weight=1)

        mora_card = self._make_card(cards)
        mora_card.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        ctk.CTkLabel(mora_card, text="💰 今日摩拉", font=(FONT, 12), text_color=DIM).pack(pady=(14, 2))
        self.mora_label = ctk.CTkLabel(mora_card, text="0", font=(FONT, 34, "bold"), text_color=ACCENT)
        self.mora_label.pack(pady=(0, 14))

        art_card = self._make_card(cards)
        art_card.grid(row=0, column=1, sticky="nsew", padx=6)
        ctk.CTkLabel(art_card, text="💠 狗粮（圣遗物）", font=(FONT, 12), text_color=DIM).pack(pady=(14, 2))
        self.artifact_label = ctk.CTkLabel(art_card, text="×0", font=(FONT, 34, "bold"), text_color=ACCENT)
        self.artifact_label.pack(pady=(0, 14))

        time_card = self._make_card(cards)
        time_card.grid(row=0, column=2, sticky="nsew", padx=(6, 0))
        ctk.CTkLabel(time_card, text="⏱ 挂机时间", font=(FONT, 12), text_color=DIM).pack(pady=(14, 2))
        self.time_label = ctk.CTkLabel(time_card, text="00:00:00", font=(FONT, 26, "bold"), text_color=TEXT)
        self.time_label.pack(pady=(6, 14))

        # 素材区（双列：怪物素材 | 普通材料）
        recent = self._make_card(page)
        recent.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        page.grid_rowconfigure(1, weight=1)

        head2 = ctk.CTkFrame(recent, fg_color="transparent")
        head2.pack(fill="x", padx=14, pady=(12, 2))
        ctk.CTkLabel(head2, text="⚔ 材料", font=(FONT, 14, "bold"), text_color=ACCENT).pack(side="left")
        self.mat_scroll = ctk.CTkScrollableFrame(recent, corner_radius=RADIUS_INNER, fg_color=CARD_INNER)
        self.mat_scroll.pack(fill="both", expand=True, padx=10, pady=(2, 10))

    # ---- 页面：素材明细 ----

    def _build_page_materials(self):
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        page.grid(row=0, column=0, sticky="nsew", padx=22, pady=18)
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)
        page.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(page, text="素材明细", font=(FONT, 20, "bold"), text_color=ACCENT).grid(
            row=0, column=0, sticky="w", pady=(0, 12))
        ctk.CTkLabel(page, text="⚔ 材料", font=(FONT, 14, "bold"), text_color=ACCENT).grid(
            row=1, column=0, sticky="w", pady=(0, 4))
        self.detail_scroll = ctk.CTkScrollableFrame(page, corner_radius=RADIUS_CARD, fg_color=CARD)
        self.detail_scroll.grid(row=2, column=0, sticky="nsew")
        self.detail_total_label = ctk.CTkLabel(page, text="", font=(FONT, 12), text_color=DIM)
        self.detail_total_label.grid(row=3, column=0, sticky="w", pady=(8, 0))
        # 保留 detail_scroll2 引用（兼容旧逻辑，不显示）
        self.detail_scroll2 = self.detail_scroll

    # ---- 页面：收益统计条 ----

    def _build_page_bar(self):
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        page.grid(row=0, column=0, sticky="nsew", padx=22, pady=18)
        page.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(page, text="收益统计条", font=(FONT, 20, "bold"), text_color=ACCENT).grid(
            row=0, column=0, sticky="w", pady=(0, 12))

        card = self._make_card(page)
        card.grid(row=1, column=0, sticky="ew")
        ctk.CTkLabel(
            card, text="直播间小窗口：摩拉 / 材料 / 狗粮 三个格子，图标在上、数量在下。",
            font=(FONT, 13), text_color=TEXT,
        ).pack(padx=20, pady=(16, 4))
        ctk.CTkLabel(
            card, text="· 打开后可以随便拖动位置，放到直播间角落\n"
                       "· 三个格子的图标已内置（默认图标）\n"
                       "· OBS 里用「窗口捕获」选「收益统计条」窗口即可上屏",
            font=(FONT, 12), text_color=DIM, justify="left",
        ).pack(padx=20, pady=(0, 12))
        self.bar_btn = ctk.CTkButton(
            card, text="📶 打开统计条", font=(FONT, 14),
            height=44, corner_radius=8, fg_color=ACCENT, hover_color=ACCENT_DARK,
            text_color="#FFFFFF", command=self.on_stat_bar_toggle,
        )
        self.bar_btn.pack(padx=20, pady=(4, 18))

    # ---- 页面：设置（可滚动，分组卡片 + 更多选项）----

    def _build_page_settings(self):
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        page.grid(row=0, column=0, sticky="nsew", padx=22, pady=18)
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(page, text="设置", font=(FONT, 20, "bold"), text_color=ACCENT).grid(
            row=0, column=0, sticky="w", pady=(0, 12))

        # 滚动容器（选项多，一页放不下）
        scroll = ctk.CTkScrollableFrame(page, corner_radius=0, fg_color="transparent")
        scroll.grid(row=1, column=0, sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)

        r = 0

        # ---- 1. 检测设置 ----
        card1 = self._make_card(scroll)
        card1.grid(row=r, column=0, sticky="ew", pady=(0, 10)); r += 1
        ctk.CTkLabel(card1, text="⚙️ 检测设置", font=(FONT, 13, "bold"), text_color=ACCENT).pack(padx=20, pady=(12, 6))

        self._setting_row(card1, "检测间隔（毫秒）", "每多少毫秒检查一次画面（默认 50，可填 10~5000）")
        self.tick_entry = ctk.CTkEntry(
            card1, font=(FONT, 13), height=32, fg_color=CARD_INNER,
            text_color=TEXT, border_color=BTN_HOVER,
        )
        self.tick_entry.insert(0, str(int(self.settings.get("tick_interval", 50))))
        self.tick_entry.pack(padx=20, pady=(0, 10), fill="x")

        self._setting_row(card1, "画面变化灵敏度", "越灵敏，掉落提示一出现就越快识别（太灵敏会耗电）")
        self.change_var = ctk.StringVar(value=str(self.settings.get("change_level", "中")))
        ctk.CTkSegmentedButton(
            card1, values=["高", "中", "低"], variable=self.change_var,
            font=(FONT, 12), fg_color=BTN, selected_color=ACCENT, selected_hover_color=ACCENT_DARK,
            text_color=TEXT, text_color_disabled=DIM,
        ).pack(padx=20, pady=(0, 12))

        # ---- 2. 识别设置 ----
        card2 = self._make_card(scroll)
        card2.grid(row=r, column=0, sticky="ew", pady=(0, 10)); r += 1
        ctk.CTkLabel(card2, text="🔍 识别设置", font=(FONT, 13, "bold"), text_color=ACCENT).pack(padx=20, pady=(12, 6))

        self._setting_row(card2, "防重复窗口（秒）", "同一提示消失多久后再出现才算新掉落（默认 1.5 秒）")
        self.event_var = ctk.StringVar(value=str(self.settings.get("event_end_window", 1.5)))
        ctk.CTkSegmentedButton(
            card2, values=["1.0", "1.5", "2.5"], variable=self.event_var,
            font=(FONT, 12), fg_color=BTN, selected_color=ACCENT, selected_hover_color=ACCENT_DARK,
            text_color=TEXT, text_color_disabled=DIM,
        ).pack(padx=20, pady=(0, 10))

        self._setting_row(card2, "文字识别频率", "越快响应越及时，越慢越省电（推荐标准）")
        self.ocr_var = ctk.StringVar(
            value={150: "快", 250: "标准", 500: "慢"}.get(int(self.settings.get("ocr_interval", 250)), "标准")
        )
        ctk.CTkSegmentedButton(
            card2, values=["快", "标准", "慢"], variable=self.ocr_var,
            font=(FONT, 12), fg_color=BTN, selected_color=ACCENT, selected_hover_color=ACCENT_DARK,
            text_color=TEXT, text_color_disabled=DIM,
        ).pack(padx=20, pady=(0, 10))

        self._setting_row(card2, "自动登记新材料", "遇到材料库里没有的名字时，自动加进材料库（推荐开启）")
        self.auto_reg_var = ctk.BooleanVar(value=bool(self.settings.get("auto_register_material", True)))
        ctk.CTkSwitch(
            card2, text="开启", variable=self.auto_reg_var, onvalue=True, offvalue=False,
            font=(FONT, 12), fg_color=ACCENT, progress_color=ACCENT_DARK,
            text_color=TEXT,
        ).pack(anchor="w", padx=20, pady=(0, 12))

        # ---- 3. 识别内容 ----
        card3 = self._make_card(scroll)
        card3.grid(row=r, column=0, sticky="ew", pady=(0, 10)); r += 1
        ctk.CTkLabel(card3, text="🎯 识别内容（想统计什么就开什么）", font=(FONT, 13, "bold"), text_color=ACCENT).pack(padx=20, pady=(12, 6))

        self.enable_mora_var = ctk.BooleanVar(value=bool(self.settings.get("enable_mora", True)))
        ctk.CTkSwitch(
            card3, text="💰 识别摩拉", variable=self.enable_mora_var, onvalue=True, offvalue=False,
            font=(FONT, 13), fg_color=ACCENT, progress_color=ACCENT_DARK, text_color=TEXT,
        ).pack(anchor="w", padx=20, pady=(4, 2))
        self.enable_mat_var = ctk.BooleanVar(value=bool(self.settings.get("enable_material", True)))
        ctk.CTkSwitch(
            card3, text="⚔ 识别怪物素材", variable=self.enable_mat_var, onvalue=True, offvalue=False,
            font=(FONT, 13), fg_color=ACCENT, progress_color=ACCENT_DARK, text_color=TEXT,
        ).pack(anchor="w", padx=20, pady=2)
        self.enable_art_var = ctk.BooleanVar(value=bool(self.settings.get("enable_artifact", True)))
        ctk.CTkSwitch(
            card3, text="💠 识别圣遗物（狗粮）", variable=self.enable_art_var, onvalue=True, offvalue=False,
            font=(FONT, 13), fg_color=ACCENT, progress_color=ACCENT_DARK, text_color=TEXT,
        ).pack(anchor="w", padx=20, pady=(2, 12))

        # ---- 4. 运行设置 ----
        card4 = self._make_card(scroll)
        card4.grid(row=r, column=0, sticky="ew", pady=(0, 10)); r += 1
        ctk.CTkLabel(card4, text="🖥 运行设置", font=(FONT, 13, "bold"), text_color=ACCENT).pack(padx=20, pady=(12, 6))

        self._setting_row(card4, "点右上角 ✕ 时", "每次询问=弹窗选择；最小化到托盘=监测继续；直接退出=关闭程序")
        _cb = {"ask": "每次询问", "tray": "最小化到托盘", "exit": "直接退出"}.get(self.settings.get("close_behavior", "ask"), "每次询问")
        self.close_btn_var = ctk.StringVar(value=_cb)
        ctk.CTkSegmentedButton(
            card4, values=["每次询问", "最小化到托盘", "直接退出"], variable=self.close_btn_var,
            font=(FONT, 12), fg_color=BTN, selected_color=ACCENT, selected_hover_color=ACCENT_DARK,
            text_color=TEXT, text_color_disabled=DIM,
        ).pack(padx=20, pady=(0, 12))

        self._setting_row(card4, "只在原神前台时识别", "切到其他应用就暂停识别，回到原神自动继续（推荐开启，避免误识别别的窗口）")
        self.only_foreground_var = ctk.BooleanVar(value=bool(self.settings.get("only_foreground", True)))
        ctk.CTkSwitch(
            card4, text="开启", variable=self.only_foreground_var, onvalue=True, offvalue=False,
            font=(FONT, 12), fg_color=ACCENT, progress_color=ACCENT_DARK, text_color=TEXT,
        ).pack(anchor="w", padx=20, pady=(0, 12))

        # ---- 6. 外观 ----
        card6 = self._make_card(scroll)
        card6.grid(row=r, column=0, sticky="ew", pady=(0, 10)); r += 1
        ctk.CTkLabel(card6, text="🎨 外观（改后重启程序生效）", font=(FONT, 13, "bold"), text_color=ACCENT).pack(padx=20, pady=(12, 6))

        self._setting_row(card6, "背景颜色", "窗口背景色（可以选任意颜色）")
        cur_bg = self.settings.get("bg_color", "经典深黑")
        if cur_bg not in theme.BG_PRESETS:
            self._custom_bg_hex = cur_bg
        self.bg_var = ctk.StringVar(value=cur_bg if cur_bg in theme.BG_PRESETS else "自定义…")
        ctk.CTkSegmentedButton(
            card6, values=list(theme.BG_PRESETS.keys()) + ["自定义…"], variable=self.bg_var,
            font=(FONT, 11), fg_color=BTN, selected_color=ACCENT, selected_hover_color=ACCENT_DARK,
            text_color=TEXT, text_color_disabled=DIM, command=self._on_pick_bg_color,
        ).pack(padx=20, pady=(0, 10))

        self._setting_row(card6, "强调色", "按钮、选中项、数字高亮的颜色")
        cur_ac = self.settings.get("accent_color", "经典蓝")
        if cur_ac not in theme.ACCENT_PRESETS:
            self._custom_accent_hex = cur_ac
        self.accent_var = ctk.StringVar(value=cur_ac if cur_ac in theme.ACCENT_PRESETS else "自定义…")
        ctk.CTkSegmentedButton(
            card6, values=list(theme.ACCENT_PRESETS.keys()) + ["自定义…"], variable=self.accent_var,
            font=(FONT, 11), fg_color=BTN, selected_color=ACCENT, selected_hover_color=ACCENT_DARK,
            text_color=TEXT, text_color_disabled=DIM, command=self._on_pick_accent_color,
        ).pack(padx=20, pady=(0, 10))

        self._setting_row(card6, "自定义背景图片", "选一张图片当窗口背景（不选=纯色背景）")
        bg_row = ctk.CTkFrame(card6, fg_color="transparent")
        bg_row.pack(fill="x", padx=20, pady=(0, 4))
        ctk.CTkButton(
            bg_row, text="🖼 选择图片…", font=(FONT, 12), height=32,
            fg_color=BTN, hover_color=BTN_HOVER, command=self._choose_bg_image,
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            bg_row, text="✖ 清除背景", font=(FONT, 12), height=32,
            fg_color=DANGER, hover_color=DANGER_HOVER, command=self._clear_bg_image,
        ).pack(side="left")
        _cur_bg_file = Path(self.settings.get("bg_image") or "").name if self.settings.get("bg_image") else ""
        self._bg_img_label = ctk.CTkLabel(
            card6,
            text=f"当前：{_cur_bg_file}" if _cur_bg_file else "未设置（纯色背景）",
            font=(FONT, 11), text_color=DIM,
        )
        self._bg_img_label.pack(anchor="w", padx=20, pady=(0, 8))

        self._setting_row(card6, "左侧栏毛玻璃效果", "需要先设置背景图片（模糊+压暗，模拟磨砂质感）")
        self.glass_var = ctk.BooleanVar(value=bool(self.settings.get("sidebar_glass", True)))
        ctk.CTkSwitch(
            card6, text="开启", variable=self.glass_var, onvalue=True, offvalue=False,
            font=(FONT, 12), fg_color=ACCENT, progress_color=ACCENT_DARK, text_color=TEXT,
        ).pack(anchor="w", padx=20, pady=(0, 12))

        # ---- 6.5 OBS 浏览器源 ----
        card_obs = self._make_card(scroll)
        card_obs.grid(row=r, column=0, sticky="ew", pady=(0, 10)); r += 1
        ctk.CTkLabel(card_obs, text="📺 连接 OBS 直播覆盖", font=(FONT, 13, "bold"), text_color=ACCENT).pack(padx=20, pady=(12, 4))
        ctk.CTkLabel(
            card_obs, text="开启后，StatGI 会提供一个本地网页地址。\n"
                           "在 OBS 里添加「浏览器源」，粘贴这个地址，\n"
                           "即可在直播画面上显示收益统计（弹幕区 + 2×2 收益 + 备注区）。",
            font=(FONT, 11), text_color=DIM, justify="left",
        ).pack(anchor="w", padx=20, pady=(0, 8))
        self.obs_var = ctk.BooleanVar(value=bool(self.settings.get("obs_browser_source", False)))
        ctk.CTkSwitch(
            card_obs, text="开启 OBS 浏览器源", variable=self.obs_var, onvalue=True, offvalue=False,
            font=(FONT, 12), fg_color=ACCENT, progress_color=ACCENT_DARK, text_color=TEXT,
            command=self._toggle_obs_source,
        ).pack(anchor="w", padx=20, pady=(0, 6))
        # 地址行
        obs_row = ctk.CTkFrame(card_obs, fg_color="transparent")
        obs_row.pack(fill="x", padx=20, pady=(0, 4))
        api_port = int(self.settings.get("api_port", 8765))
        self._obs_addr_label = ctk.CTkLabel(
            obs_row, text=f"地址：http://127.0.0.1:{api_port}/overlay",
            font=(FONT, 11), text_color=TEXT,
        )
        self._obs_addr_label.pack(side="left")
        ctk.CTkButton(
            obs_row, text="复制", font=(FONT, 11), width=52, height=26,
            corner_radius=8, fg_color=BTN, hover_color=BTN_HOVER, command=self._copy_obs_addr,
        ).pack(side="right")
        ctk.CTkLabel(
            card_obs, text="备注：透明背景，可直接叠在游戏画面上。",
            font=(FONT, 10), text_color=DIM,
        ).pack(anchor="w", padx=20, pady=(0, 12))

        # ---- 7. 关于 / 更新 ----
        card5 = self._make_card(scroll)
        card5.grid(row=r, column=0, sticky="ew", pady=(0, 10)); r += 1
        ctk.CTkLabel(card5, text="ℹ️ 关于 / 更新", font=(FONT, 13, "bold"), text_color=ACCENT).pack(padx=20, pady=(12, 4))
        ctk.CTkLabel(
            card5, text="StatGI V0.4（测试版）\n"
                     "· 识别只靠文字（OCR），不读内存、不控制游戏\n"
                     "· 防重复统计：同一个掉落提示只统计一次\n"
                     "· 数据保存在程序旁边的 data 文件夹",
            font=(FONT, 12), text_color=DIM, justify="left",
        ).pack(padx=20, pady=(0, 8))
        upd_row = ctk.CTkFrame(card5, fg_color="transparent")
        upd_row.pack(fill="x", padx=20, pady=(0, 4))
        ctk.CTkButton(
            upd_row, text="🔍 检测更新", font=(FONT, 13), height=34,
            corner_radius=8, fg_color=ACCENT, hover_color=ACCENT_DARK, text_color="#FFFFFF",
            command=self.on_check_update,
        ).pack(side="left")
        self.update_status_label = ctk.CTkLabel(
            upd_row, text="", font=(FONT, 11), text_color=DIM,
        )
        self.update_status_label.pack(side="left", padx=10)
        ctk.CTkLabel(
            card5, text="检测更新会访问 GitHub Releases，需要联网。",
            font=(FONT, 10), text_color=DIM,
        ).pack(anchor="w", padx=20, pady=(0, 12))

        # 保存按钮（固定在底部）
        ctk.CTkButton(
            page, text="💾 保存设置", font=(FONT, 14),
            height=42, corner_radius=8, fg_color=ACCENT, hover_color=ACCENT_DARK,
            text_color="#FFFFFF", command=self.on_save_settings,
        ).grid(row=2, column=0, sticky="ew", pady=(10, 0))

    def _setting_row(self, card, title, desc):
        ctk.CTkLabel(card, text=title, font=(FONT, 13), text_color=TEXT).pack(padx=20, pady=(6, 0), anchor="w")
        ctk.CTkLabel(card, text=desc, font=(FONT, 11), text_color=DIM).pack(padx=20, pady=(0, 4), anchor="w")

    # ---------- 外观设置 ----------

    def _on_pick_bg_color(self, value):
        """点「自定义…」时打开颜色选择器"""
        if value != "自定义…":
            return
        prev = self.bg_var.get()
        c = colorchooser.askcolor(title="选择背景颜色", color=BG)[1]
        if c:
            self._custom_bg_hex = c
        else:
            self.bg_var.set(prev)

    def _on_pick_accent_color(self, value):
        if value != "自定义…":
            return
        prev = self.accent_var.get()
        c = colorchooser.askcolor(title="选择强调色", color=ACCENT)[1]
        if c:
            self._custom_accent_hex = c
        else:
            self.accent_var.set(prev)

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
        self._bg_img_label.configure(text=f"当前：{Path(p).name}")
        self._apply_background()  # 立即预览
        messagebox.showinfo("已选择", "背景已预览。点「保存设置」后，下次启动程序正式生效。")

    def _clear_bg_image(self):
        """清除背景图片，恢复纯色"""
        self.settings["bg_image"] = ""
        try:
            self._bg_img_label.configure(text="未设置（纯色背景）")
        except Exception:
            pass
        self._apply_background()

    def on_save_settings(self):
        """保存并应用设置"""
        try:
            val = int(self.tick_entry.get().strip())
            self.settings["tick_interval"] = max(10, min(5000, val))
        except Exception:
            pass
        change_map = {"高": 2.0, "中": 4.0, "低": 8.0}
        self.settings["change_threshold"] = change_map.get(self.change_var.get(), 4.0)
        try:
            self.settings["event_end_window"] = float(self.event_var.get())
        except Exception:
            pass
        ocr_map = {"快": 150, "标准": 250, "慢": 500}
        self.settings["ocr_interval"] = ocr_map.get(self.ocr_var.get(), 250)
        self.settings["auto_register_material"] = bool(self.auto_reg_var.get())
        self.settings["enable_mora"] = bool(self.enable_mora_var.get())
        self.settings["enable_material"] = bool(self.enable_mat_var.get())
        self.settings["enable_artifact"] = bool(self.enable_art_var.get())
        self.settings["only_foreground"] = bool(self.only_foreground_var.get()) if hasattr(self, "only_foreground_var") else self.settings.get("only_foreground", True)
        self.settings["close_behavior"] = {"每次询问": "ask", "最小化到托盘": "tray", "直接退出": "exit"}.get(
            self.close_btn_var.get(), "ask"
        )
        # 外观
        bg_sel = self.bg_var.get()
        if bg_sel == "自定义…":
            self.settings["bg_color"] = getattr(self, "_custom_bg_hex", None) or BG
        else:
            self.settings["bg_color"] = bg_sel
        ac_sel = self.accent_var.get()
        if ac_sel == "自定义…":
            self.settings["accent_color"] = getattr(self, "_custom_accent_hex", None) or ACCENT
        else:
            self.settings["accent_color"] = ac_sel
        self.settings["bg_image"] = self.settings.get("bg_image", "")
        self.settings["sidebar_glass"] = bool(self.glass_var.get())
        self.settings["obs_browser_source"] = bool(self.obs_var.get())
        config_manager.save_settings(self.settings)
        # 应用到正在运行的检测器
        if self.detector:
            self.detector.settings = self.settings  # 识别开关、自动登记等直接读 settings
            self.detector.change_threshold = float(self.settings.get("change_threshold", 4.0))
            self.detector.tracker.end_window = float(self.settings.get("event_end_window", 1.5))
            self.detector.ocr_interval = float(self.settings.get("ocr_interval", 250)) / 1000.0
        messagebox.showinfo("已保存", "设置已保存并生效。\n（背景色 / 强调色等外观设置，会在下次启动程序时显示）")

    # ---- 通用卡片 ----

    def _make_card(self, parent):
        return ctk.CTkFrame(parent, corner_radius=RADIUS_CARD, fg_color=CARD,
                            border_width=1, border_color=theme.BORDER)

    # ================= 页面切换 =================

    def _show_page(self, key):
        self._current_page = key
        pages = {"launch": 0, "home": 1, "materials": 2, "bar": 3, "settings": 4}
        for i, child in enumerate(self.content.winfo_children()):
            if i != pages[key]:
                child.grid_remove()
            else:
                child.grid()
        for k, btn in self.nav_btns.items():
            if k == key:
                btn.configure(fg_color=NAV_ON, text_color=ACCENT, font=(FONT, 13, "bold"))
            else:
                btn.configure(fg_color="transparent", text_color=DIM, font=(FONT, 13))

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
                            text=f"{desc}  ({time.strftime('%H:%M:%S', time.localtime(ts))})"
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
                elif action == "exit":
                    self.on_exit()

            # 3. 刷新界面（内部只在数据变化时重建列表）
            self._refresh_ui()
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
        self.demo_active = False
        self.demo_btn.configure(text="🎬 演示模式（模拟掉落，自动统计）")
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
        self._set_status(mode_text, GOOD)
        self.start_btn.configure(text="⏸ 停止监测")

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
        if self.demo_active:
            self.demo_active = False
            self.demo_btn.configure(text="🎬 演示模式（模拟掉落，自动统计）")
        self._set_status("已暂停", BAD)
        self.start_btn.configure(text="▶ 开始监测")

    def on_demo(self):
        """演示模式：不用游戏也能看到统计流程跑起来"""
        if self.demo_active:
            # 退出演示
            self.stop_monitor()
            self._refresh_region_state()
            return
        # 启动演示
        if self.monitoring:
            self.stop_monitor()
        self.demo_active = True
        self._detect_stop = threading.Event()
        self._detect_queue = queue.Queue()
        self._detect_err_streak = 0
        self._detect_thread = threading.Thread(
            target=self._demo_loop, args=(), daemon=True
        )
        self._detect_thread.start()
        self.monitoring = True
        self._monitor_start = time.monotonic()
        self._set_status("演示模式（模拟掉落）", ACCENT)
        self.start_btn.configure(text="⏸ 停止监测")
        self.demo_btn.configure(text="⏹ 退出演示")

    def _demo_loop(self):
        """演示模式的检测线程（模拟画面，走完整识别流程）"""
        stop_ev = self._detect_stop  # 局部引用，避免竞态
        try:
            import demo
            det = demo.create_demo_detector(
                {"x": 0, "y": 0, "w": 700, "h": 160},
                self.stats,
                {"event_end_window": 2.0, "change_threshold": 2.0},
            )
        except Exception:
            try:
                self._detect_queue.put(("error", "演示启动失败"))
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
                    self._detect_err_streak += 1
                    if self._detect_err_streak > 20:
                        try:
                            self._detect_queue.put(("error", "演示出错"))
                        except Exception:
                            pass
                        break
                ev = det.last_event
                if ev is not None and ev[0] != last_ts:
                    last_ts = ev[0]
                    try:
                        self._detect_queue.put(("event", ev))
                    except Exception:
                        pass
                stop_ev.wait(0.05)
        finally:
            try:
                det.close()
            except Exception:
                pass
            self.detector = None

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
                current = "0.4"
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
        """单独清空挂机时间（收益数据不动）。正在监测时从中断点重新计时。"""
        if not messagebox.askyesno("确认", "确定清空挂机时间吗？\n（摩拉、材料等收益不受影响）"):
            return
        self.stats.clear_running_seconds()
        # 若正在监测，重置本次开始时间，让挂机时间从 0 重新累计
        if self.monitoring:
            self._monitor_start = time.monotonic()
        self._refresh_ui()
        messagebox.showinfo("已清空", "挂机时间已清空")

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

    def _refresh_region_state(self):
        r = self.settings.get("region")
        if not r:
            # 自动模式：不用框选，程序自动找游戏窗口
            self._set_status("未框选（自动检测游戏窗口）", DIM)
            self.start_btn.configure(state="normal", text="▶ 开始监测")
            try:
                self.launch_region_label.configure(text="自动检测游戏窗口（也可「重新框选」手动指定）")
            except Exception:
                pass
        else:
            self.start_btn.configure(state="normal", text="▶ 开始监测")
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
        try:
            # 今日摩拉（千分位）
            self.mora_label.configure(text=f"{self.stats.mora:,}")
            # 挂机时间
            total = self.stats.running_seconds
            if self.monitoring and self._monitor_start:
                total += int(time.monotonic() - self._monitor_start)
            self.time_label.configure(text=fmt_time(total))
            # 狗粮
            self.artifact_label.configure(text=f"×{self.stats.artifact}")
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
                font=(FONT, 12), text_color=DIM,
            ).pack(pady=16)
            return
        for name, count in items:
            row = ctk.CTkFrame(self.mat_scroll, fg_color="transparent")
            row.pack(fill="x", padx=6, pady=2)
            ctk.CTkLabel(row, text=name, font=(FONT, 13), text_color=TEXT).pack(side="left")
            ctk.CTkLabel(row, text=f"×{count}", font=(FONT, 13, "bold"), text_color=ACCENT).pack(side="right")

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
                font=(FONT, 13), text_color=DIM,
            ).pack(pady=20)
        else:
            for i, (name, count) in enumerate(items, 1):
                row = ctk.CTkFrame(self.detail_scroll, fg_color=CARD_INNER, corner_radius=8)
                row.pack(fill="x", padx=8, pady=3)
                ctk.CTkLabel(row, text=f"{i:>2}", font=(FONT, 13), text_color=DIM, width=30).pack(side="left", padx=(10, 2), pady=8)
                ctk.CTkLabel(row, text=name, font=(FONT, 14), text_color=TEXT).pack(side="left", padx=6, pady=8)
                ctk.CTkLabel(row, text=f"×{count}", font=(FONT, 14, "bold"), text_color=ACCENT).pack(side="right", padx=14)
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
        """最小化按钮：隐藏窗口到托盘（稳定不卡死）。

        之前用"移到屏幕外"的方案在某些系统上会触发重绘问题导致卡死/闪退，
        改为最稳定的 withdraw() 隐藏。托盘图标和任务栏按钮都能呼出。
        """
        try:
            self._min_saved_pos = (self.winfo_x(), self.winfo_y())
        except Exception:
            self._min_saved_pos = None
        self._minimized = True
        self.withdraw()

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
            font=(FONT, 14, "bold"), text_color=TEXT,
        ).pack(pady=(22, 4))
        ctk.CTkLabel(
            dlg, text="最小化后监测会继续运行",
            font=(FONT, 11), text_color=DIM,
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
            row, text="🗑 关闭程序", font=(FONT, 13), width=100, height=36,
            fg_color=DANGER, hover_color=DANGER_HOVER, text_color=TEXT, command=_do_exit,
        ).pack(side="left", padx=6)
        ctk.CTkButton(
            row, text="📌 最小化到托盘", font=(FONT, 13), width=130, height=36,
            fg_color=ACCENT, hover_color=ACCENT_DARK, text_color="#FFFFFF", command=_do_tray,
        ).pack(side="left", padx=6)
        ctk.CTkButton(
            row, text="取消", font=(FONT, 13), width=80, height=36,
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
