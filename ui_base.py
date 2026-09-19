# -*- coding: utf-8 -*-
"""界面公共的东西：主题常量 + 小工具 + 全局热键的键名转换。

所有界面模块（ui_glass / ui_pages / ui_actions / win_shell）都从这里取，
app.py 也从这里转出去，避免各自抄一份。
"""
from pathlib import Path

import theme
import paths
from fonts import FONT

BASE_DIR = paths.app_dir()
ICONS_DIR = paths.icons_dir()

# ---- 主题常量（实际值都在 theme.py，这里只是转出来给界面用）----
BG = theme.BG                    # 窗口底色
SIDEBAR = theme.SIDEBAR          # 左侧栏
HEADER = theme.HEADER            # 顶栏
CARD = theme.CARD                # 卡片
CARD_INNER = theme.CARD_INNER    # 卡片内部的浅色区域
ACCENT = theme.ACCENT            # 强调色
ACCENT_DARK = theme.ACCENT_DARK
TEXT = theme.TEXT
DIM = theme.DIM                  # 次要文字
GOOD = theme.GOOD
BAD = theme.BAD
NAV_ON = theme.NAV_ON            # 选中的导航项
BTN = theme.BTN
BTN_HOVER = theme.BTN_HOVER
DANGER = theme.DANGER
DANGER_HOVER = theme.DANGER_HOVER
RADIUS_CARD = theme.RADIUS_CARD
RADIUS_BTN = theme.RADIUS_BTN
RADIUS_INNER = theme.RADIUS_INNER

# 开关「关闭」时的轨道颜色（灰色，这样一眼能看出开还是关）
SWITCH_OFF = "#5A5A5A"


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
