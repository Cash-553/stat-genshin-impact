# -*- coding: utf-8 -*-
"""StatGI Qt 版 · 系统托盘 + 全局热键

托盘：Qt 自带的 QSystemTrayIcon（不用 pystray 了，省一个依赖）。
热键：Windows 的 RegisterHotKey，代码直接沿用 Tk 版验证过的那套
      （只处理 WM_HOTKEY，其它消息原样转发）。
"""
from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QAction
from PySide6.QtWidgets import QSystemTrayIcon, QMenu

from qt_theme import ACCENT


# ---- 热键字符串解析（从 ui_base.py 搬过来的，这样 Qt 版不依赖任何 Tk 文件）----
def keysym_to_vk(ks):
    """键名（F9 / S / SPACE…）-> Windows 虚拟键码"""
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


def parse_hotkey(s):
    """字符串 -> (mods, vk)；无法解析返回 None

    mods 用 Windows 的 MOD_* 值：Alt=0x1 Ctrl=0x2 Shift=0x4 Win=0x8
    """
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
    vk = keysym_to_vk(key)
    if vk is None:
        return None
    return mods, vk


def _fallback_icon():
    """没找到 ico 就画一个简单的"""
    pm = QPixmap(64, 64)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setBrush(QColor(ACCENT))
    p.setPen(QColor(0, 0, 0, 0))
    p.drawEllipse(4, 4, 56, 56)
    p.setPen(QColor("#08222E"))
    p.setFont(QFont("Microsoft YaHei UI", 26, QFont.Bold))
    p.drawText(pm.rect(), 0x0084, "S")     # AlignCenter
    p.end()
    return QIcon(pm)


class Tray(QObject):
    """托盘图标 + 菜单"""

    def __init__(self, win, icon_path=None, app_icon=None):
        super().__init__(win)
        self.win = win
        # 注意：QIcon 只接受 str / QPixmap，给 Path 会报 TypeError
        icon = None
        try:
            if icon_path is not None:
                p = str(icon_path)
                if p and __import__("os").path.exists(p):
                    icon = QIcon(p)
        except Exception:
            icon = None
        if icon is None or icon.isNull():
            icon = app_icon if (app_icon and not app_icon.isNull()) else _fallback_icon()
        self.icon = QSystemTrayIcon(icon, win)
        self.icon.setToolTip("StatGI 原神收益统计器")

        menu = QMenu()
        self.act_show = QAction("显示主窗口", menu)
        self.act_show.triggered.connect(win.restore_from_tray)
        menu.addAction(self.act_show)
        menu.addSeparator()
        self.act_start = QAction("▶  开始监测", menu)
        self.act_start.triggered.connect(lambda: win.state.start())
        menu.addAction(self.act_start)
        self.act_stop = QAction("⏸  停止监测", menu)
        self.act_stop.triggered.connect(lambda: win.state.stop())
        menu.addAction(self.act_stop)
        menu.addSeparator()
        self.act_data = QAction("📂 打开数据文件夹", menu)
        self.act_data.triggered.connect(win.open_data_dir)
        menu.addAction(self.act_data)
        self.act_exit = QAction("❌ 退出程序", menu)
        self.act_exit.triggered.connect(win.really_quit)
        menu.addAction(self.act_exit)

        self.icon.setContextMenu(menu)
        self.icon.activated.connect(self._on_activated)
        self.icon.show()

        # 菜单文字跟着监测状态走（只在变了的时候改）
        win.state.status_changed.connect(self._sync)

    def _sync(self, *_a):
        on = self.win.state.monitoring
        self.act_start.setEnabled(not on)
        self.act_stop.setEnabled(on)

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:      # 左键单击
            self.win.restore_from_tray()

    def notify(self, title, msg):
        try:
            self.icon.showMessage(title, msg, QSystemTrayIcon.Information, 3000)
        except Exception:
            pass


class HotkeyManager(QObject):
    """全局热键（开始/停止监测）

    做法：每 120ms 用 GetAsyncKeyState 轮询一次组合键。
    为什么不用 RegisterHotKey？
      · RegisterHotKey 要子类化窗口过程才能收到 WM_HOTKEY，
        而 Tk 版就是在那上面踩过坑（吞掉消息导致任务栏最小化/还原失灵）
      · 轮询只是读一下键盘状态，不碰窗口过程，也没有回调用悬空的风险
    代价：轮询有极小开销；极快的点按（<120ms）可能漏掉一次。
    """

    def __init__(self, win, on_trigger):
        super().__init__(win)
        self.win = win
        self.on_trigger = on_trigger
        self._down = False
        self._cache = None            # 上次解析出来的 (mods, vk, 原始字符串)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._check)
        self._timer.start(120)

    def _check(self):
        try:
            import ctypes
            want = str((self.win.state.settings or {}).get("hotkey", "关闭"))
            # 只在设置里那条热键字符串改了之后才重新解析
            if self._cache is None or self._cache[1] != want:
                self._cache = (parse_hotkey(want), want)
            parsed = self._cache[0]
            if not parsed:
                self._down = False
                return
            mods, vk = parsed
            u = ctypes.windll.user32
            keys = []
            if mods & 0x0002:
                keys.append(0x11)     # Ctrl
            if mods & 0x0001:
                keys.append(0x12)     # Alt
            if mods & 0x0004:
                keys.append(0x10)     # Shift
            if mods & 0x0008:
                keys.append(0x5B)     # Win
            keys.append(vk)
            pressed = all(u.GetAsyncKeyState(k) & 0x8000 for k in keys)
            if pressed and not self._down:
                self._down = True
                self.on_trigger()
            elif not pressed:
                self._down = False
        except Exception:
            pass
