# -*- coding: utf-8 -*-
"""StatGI Qt 版 · 配色与样式表

颜色直接复用根目录的 theme.py —— 也就是你在「设置 → 外观」里选的
背景色 / 强调色，Qt 版会自动跟着变，不需要再维护一份。

面板透明度来自 config/settings.json 的 panel_opacity（0~1）。
"""
import theme

# ---- 颜色（跟 Tk 版共用同一份 theme.py）----
BG = theme.BG
SIDEBAR = theme.SIDEBAR
HEADER = theme.HEADER
CARD = theme.CARD
CARD_INNER = theme.CARD_INNER
ACCENT = theme.ACCENT
ACCENT_DARK = theme.ACCENT_DARK
TEXT = theme.TEXT
DIM = theme.DIM
BORDER = theme.BORDER
BTN = theme.BTN
BTN_HOVER = theme.BTN_HOVER
DANGER = theme.DANGER
DANGER_HOVER = theme.DANGER_HOVER
SWITCH_OFF = "#5A5A5A"

RADIUS_CARD = 12
RADIUS_BTN = 8
RADIUS_WINDOW = 14

FONT = "Microsoft YaHei UI"


def reload_colors(settings):
    """按设置里选的背景色 / 强调色，**就地**更新本模块的颜色。

    这些颜色是模块级变量，所以别的模块必须写
        import qt_theme as T
        ... T.TEXT / T.ACCENT ...
    不能写 `from qt_theme import TEXT` —— 那是导入时绑定死的，
    改颜色不会生效（这正是"换背景色没反应"的原因）。

    改完颜色之后重建页面，新颜色立刻就应用上了，不用重启。
    """
    global BG, SIDEBAR, HEADER, CARD, CARD_INNER, ACCENT, ACCENT_DARK
    global TEXT, DIM, BORDER, BTN, BTN_HOVER, DANGER, DANGER_HOVER
    try:
        import importlib
        importlib.reload(theme)      # theme.py 导入时按设置算颜色，重导即可
    except Exception:
        return
    BG = theme.BG
    SIDEBAR = theme.SIDEBAR
    HEADER = theme.HEADER
    CARD = theme.CARD
    CARD_INNER = theme.CARD_INNER
    ACCENT = theme.ACCENT
    ACCENT_DARK = theme.ACCENT_DARK
    TEXT = theme.TEXT
    DIM = theme.DIM
    BORDER = theme.BORDER
    BTN = theme.BTN
    BTN_HOVER = theme.BTN_HOVER
    DANGER = theme.DANGER
    DANGER_HOVER = theme.DANGER_HOVER


def hex_rgb(h, fallback=(36, 36, 36)):
    """'#RRGGBB' -> (r, g, b)"""
    try:
        h = h.lstrip("#")
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except Exception:
        return fallback


def rgba(color, alpha):
    """颜色 + 透明度(0~255) -> Qt 样式表用的 rgba(...)"""
    r, g, b = hex_rgb(color)
    return f"rgba({r},{g},{b},{max(0, min(255, int(alpha)))})"


# ---- 面板透明度：读设置，0~1 -> 0~255 ----
def panel_alpha(settings):
    try:
        op = float(settings.get("panel_opacity", 0.5))
    except Exception:
        op = 0.5
    return int(max(0.0, min(1.0, op)) * 255)


# ============================================================
#  样式表片段
# ============================================================
def card_qss(alpha=None, radius=RADIUS_CARD):
    """卡片：半透明底 + 细边框 + 圆角"""
    a = 150 if alpha is None else alpha
    return (f"QFrame#card {{ background: {rgba(CARD, a)};"
            f" border-radius: {radius}px;"
            f" border: 1px solid {rgba('#FFFFFF', 16)}; }}")


def label_qss(color=TEXT, size=13, bold=False):
    w = " font-weight:600;" if bold else ""
    return f"color:{color}; font-family:'{FONT}'; font-size:{size}px;{w}"


def title_qss(size=22):
    return f"color:{ACCENT}; font-family:'{FONT}'; font-size:{size}px; font-weight:700;"


def btn_qss(kind="normal", alpha=None):
    """按钮：normal / accent / danger"""
    a = 150 if alpha is None else alpha
    if kind == "accent":
        bg, hv, fg = rgba(ACCENT, max(160, a + 50)), rgba(ACCENT, 255), "#08222E"
    elif kind == "danger":
        bg, hv, fg = rgba(DANGER, max(140, a + 40)), rgba(DANGER_HOVER, 230), TEXT
    else:
        bg, hv, fg = rgba(BTN, a + 60), rgba(BTN_HOVER, a + 90), TEXT
    return (f"QPushButton {{ background:{bg}; color:{fg}; border:none;"
            f" border-radius:{RADIUS_BTN}px; font-family:'{FONT}'; font-size:14px;"
            f" padding:6px 16px; }}"
            f"QPushButton:hover {{ background:{hv}; }}"
            f"QPushButton:disabled {{ color:{DIM}; background:{rgba(BTN, 90)}; }}")


def entry_qss(alpha=None):
    a = 150 if alpha is None else alpha
    return (f"QLineEdit {{ background:{rgba('#FFFFFF', 22)}; color:{TEXT}; border:none;"
            f" border-radius:{RADIUS_BTN}px; padding:6px 10px;"
            f" font-family:'{FONT}'; font-size:13px; }}"
            f"QLineEdit:focus {{ border:1px solid {ACCENT}; }}")


def combo_qss():
    return (f"QComboBox {{ background:{rgba('#FFFFFF', 22)}; color:{TEXT}; border:none;"
            f" border-radius:{RADIUS_BTN}px; padding:6px 10px;"
            f" font-family:'{FONT}'; font-size:13px; }}"
            f"QComboBox::drop-down {{ border:none; width:22px; }}"
            f"QComboBox QAbstractItemView {{ background:{CARD}; color:{TEXT};"
            f" selection-background-color:{ACCENT}; border:none; outline:none; }}")


def slider_qss():
    return ("QSlider::groove:horizontal { height:6px;"
            " background: rgba(255,255,255,30); border-radius:3px; }"
            f"QSlider::sub-page:horizontal {{ background:{ACCENT}; border-radius:3px; }}"
            f"QSlider::handle:horizontal {{ background:{ACCENT}; width:16px; height:16px;"
            f" margin:-6px 0; border-radius:8px; }}")


def switch_qss():
    return ("QCheckBox { spacing:0; }"
            f"QCheckBox::indicator {{ width:46px; height:24px; border-radius:12px;"
            f" background:{SWITCH_OFF}; }}"
            f"QCheckBox::indicator:checked {{ background:{ACCENT}; }}")


def scroll_qss():
    """滚动条：细一点，半透明"""
    return (f"QScrollArea {{ background:transparent; border:none; }}"
            f"QScrollArea > QWidget > QWidget {{ background:transparent; }}"
            f"QScrollBar:vertical {{ background:transparent; width:10px; margin:0; }}"
            f"QScrollBar::handle:vertical {{ background:{rgba('#FFFFFF', 55)};"
            f" border-radius:5px; min-height:30px; }}"
            f"QScrollBar::handle:vertical:hover {{ background:{rgba('#FFFFFF', 90)}; }}"
            f"QScrollBar::add-line, QScrollBar::sub-line {{ height:0; }}"
            f"QScrollBar::add-page, QScrollBar::sub-page {{ background:transparent; }}")
