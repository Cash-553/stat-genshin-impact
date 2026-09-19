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

# 界面的公共常量与小工具集中在 ui_base（各界面模块都从这里取）
from ui_base import (
    BASE_DIR, ICONS_DIR, BG, SIDEBAR, HEADER, CARD, CARD_INNER,
    ACCENT, ACCENT_DARK, TEXT, DIM, SWITCH_OFF, GOOD, BAD, NAV_ON,
    BTN, BTN_HOVER, DANGER, DANGER_HOVER,
    RADIUS_CARD, RADIUS_BTN, RADIUS_INNER, FONT,
    fmt_time, HOTKEY_ID, WM_HOTKEY,
    _keysym_to_vk, _hotkey_name, _parse_hotkey,
)
from ui_glass import GlassMixin
from ui_pages import PagesMixin
from ui_actions import ActionsMixin
from ui_monitor import MonitorMixin
from ui_settings import SettingsMixin
from win_shell import WindowShellMixin

# 界面主题（BetterGI 风格）
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class MainApp(WindowShellMixin, GlassMixin, PagesMixin, SettingsMixin,
              ActionsMixin, MonitorMixin, ctk.CTk):
    """主窗口。

    代码按功能拆在几个 mixin 里（都在本目录，方法原样搬过去，行为不变）：
      - WindowShellMixin (win_shell.py) 无边框窗口 / 任务栏 / 热键 / 托盘 / 关闭
      - GlassMixin       (ui_glass.py)  自定义背景 + 半透明玻璃界面
      - PagesMixin       (ui_pages.py)  各页面搭建 + 卡片工厂 + 页面切换
      - SettingsMixin    (ui_settings.py) 设置读写 + 设置项回调 + 开发者选项
      - ActionsMixin     (ui_actions.py)  清空/记录/材料/更新/统计条/接口
      - MonitorMixin     (ui_monitor.py)  主循环 + 监测控制 + 界面刷新
    剩下的窗口布局、设置读写、监测控制、界面刷新等还在本文件。
    """
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

    # ---------- 全局热键 ----------

    # ---------- 无边框窗口：拖动 & 边缘调整大小 ----------

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

    # ---- 颜色小工具 ----

    # ---- 玻璃底图（整窗，带缓存）----

    # ---- 贴图 / 清理 ----

    # ---- 布局变化时只重贴动过的控件 ----

    # ---- 递归给整棵控件树贴玻璃 ----

    # ---- 总入口 ----

    # ---- 页面：启动（默认首页）----

    # ---- 页面：今日统计 ----

    # ---- 材料明细 展开/收起（原「素材明细」页已合并进「今日统计」）----

    # ---- 页面：收益统计条 ----

    # ---- 页面：收益记录（每次「开始监测→停止监测」记一条）----

    # ---- 页面：设置（标签页 + 分组卡片）----

    # ---------- 折叠区域的内部内容 ----------

    # ---------- 全局热键：按键捕获 ----------

    # ---------- 开发者选项（AI 样本采集）----------

    # ---------- 外观设置 ----------

    # ---- 通用卡片 ----

    # ================= 页面切换 =================

    # ================= 主循环 =================

    # ================= 监测控制 =================

    # ================= 界面刷新 =================

    # ================= 数据接口 =================

    # ================= 窗口控制 =================

if __name__ == "__main__":
    # 先把「出错记录」装好：打包版没有控制台，异常不写文件就等于消失
    from errlog import install_hooks
    install_hooks()

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
