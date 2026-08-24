# -*- coding: utf-8 -*-
"""
统一主题配色（Win11 深色 Fluent Dark 风格）

颜色从 config/settings.json 的「外观设置」读取，未设置时用默认值。
所有界面文件都从这里取色，保持一致。改外观后需重启程序生效。
"""
import sys

# Win11 Fluent Dark 预设色板
BG_PRESETS = {
    "经典深黑": "#1C1C1C",    # Win11 深色 Mica 基底
    "深夜蓝": "#1B2430",
    "墨绿": "#1C2620",
    "暖灰": "#202020",
}
ACCENT_PRESETS = {
    "经典蓝": "#4CC2FF",      # Win11 强调蓝（更亮）
    "翠绿": "#6CCB5F",
    "炫紫": "#C586C0",
    "金黄": "#FFD966",
    "珊瑚红": "#FF99A0",
}


def _to_hex(v):
    if isinstance(v, str):
        v = v.strip()
        if v.startswith("#") and len(v) == 7:
            try:
                int(v[1:], 16)
                return v
            except Exception:
                return None
    return None


def _shade(hex_color, factor):
    try:
        r = int(hex_color[1:3], 16)
        g = int(hex_color[3:5], 16)
        b = int(hex_color[5:7], 16)
        r = max(0, min(255, int(r * factor)))
        g = max(0, min(255, int(g * factor)))
        b = max(0, min(255, int(b * factor)))
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return hex_color


def _load():
    try:
        from config_manager import load_settings
        s = load_settings() or {}
    except Exception:
        s = {}
    bg_sel = s.get("bg_color") or "经典深黑"
    if bg_sel in BG_PRESETS:
        bg = BG_PRESETS[bg_sel]
    else:
        bg = _to_hex(bg_sel) or BG_PRESETS["经典深黑"]
    ac_sel = s.get("accent_color") or "经典蓝"
    if ac_sel in ACCENT_PRESETS:
        accent = ACCENT_PRESETS[ac_sel]
    else:
        accent = _to_hex(ac_sel) or ACCENT_PRESETS["经典蓝"]
    return bg, accent


_BG, _ACCENT = _load()

# ---------- Win11 Fluent Dark ----------
BG = _BG                       # 窗口背景（Mica 深色基底）
SIDEBAR = _shade(_BG, 0.92)    # 侧边栏（略深）
HEADER = _shade(_BG, 0.85)     # 顶部标题条
CARD = _shade(_BG, 1.12)       # 卡片（略亮）
CARD_INNER = _shade(_BG, 1.25) # 列表行 / 内嵌区域
BORDER = _shade(_BG, 1.10)     # 卡片描边（很浅，模拟 Win11 描边）
ACCENT = _ACCENT
ACCENT_DARK = _shade(_ACCENT, 0.75)
TEXT = "#F5F5F5"
DIM = "#9D9D9D"
GOOD = _ACCENT
BAD = "#A0A0A0"
NAV_ON = _shade(_BG, 1.3)
BTN = _shade(_BG, 1.3)
BTN_HOVER = _shade(_BG, 1.5)
DANGER = _shade(_BG, 1.6)
DANGER_HOVER = _shade(_BG, 1.8)

# Win11 字体（优先 Segoe UI Variable，回退 Segoe UI / 微软雅黑）
FONT = "Segoe UI Variable"
FONT_FALLBACK = ["Segoe UI Variable Text", "Segoe UI", "Microsoft YaHei UI"]

# Win11 大圆角
RADIUS_CARD = 12     # 卡片圆角
RADIUS_BTN = 8       # 按钮圆角
RADIUS_INNER = 8     # 内嵌区域圆角
RADIUS_FULL = 16     # 大圆角（胶囊）
