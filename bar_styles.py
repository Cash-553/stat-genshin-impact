# -*- coding: utf-8 -*-
"""桌面悬浮窗的样式库 —— 像绘画软件那样，每个框都能单独调。

两层结构：
    **全局**（所有框共用的）
        layout / slot_w / slot_h / spacing / radius / 底色 / 描边 / 字号 …

    **逐格覆盖**（overrides）
        某个框想跟别人不一样，就单独写一份。比如 OBS 那条：
            摩拉格数字金色、狗粮格淡紫、时间格青色而且字号小一点
            材料/狗粮的数字前面还要加个「×」

内置两套：
    经典     —— 一直以来的样子（横排小卡片 + 图标 + 数字）
    直播间   —— **跟仓库里的「直播间美化.html」逐字对齐**

用户可以在「管理样式」里自己新建任意多套，存到 ``data/bar_styles.json``。
"""
import json

from pathlib import Path

import paths

DATA_DIR = paths.app_dir() / "data"
STYLES_FILE = DATA_DIR / "bar_styles.json"

SLOT_KEYS = ("slot1", "slot2", "slot3", "slot4")
SLOT_NAMES = {"slot1": "摩拉", "slot2": "材料",
              "slot3": "狗粮", "slot4": "挂机时间"}
# 下拉/列表里用的显示名（前面那个是"全部一起改"）
SCOPE_ALL = "__all__"
SCOPE_LABEL = {SCOPE_ALL: "全部（一起改）"}
SCOPE_LABEL.update({k: SLOT_NAMES[k] for k in SLOT_KEYS})

# 每一项：(键, 中文名, 说明, 类型, 范围/选项)
#   int        滑块，arg = (最小, 最大)
#   choice     下拉，arg = [(显示名, 值), ...]
#   color      取色器（必须有颜色）
#   color_opt  取色器，可留空
#   bool       勾选框
#   text       单行输入
FIELDS = [
    # ---- 全局：怎么摆 ----
    ("layout",       "排列方式",     "三个格子的摆放方向",            "choice",
     [("横排", "row"), ("竖排", "column"), ("2×2", "grid"), ("自由摆放", "free")], "all"),
    ("spacing",      "格子间距",     "格子之间留多少空",              "int", (0, 40), "all"),

    # ---- 每个框都能单独调的 ----
    ("slot_w",       "框的宽度",     "宽高分开设 → 想多扁多扁",        "int", (30, 260), "slot"),
    ("slot_h",       "框的高度",     "跟宽度不一样就是长方形",         "int", (30, 260), "slot"),
    ("radius",       "框的圆角",     "0=直角；拉到高度一半就是圆的",    "int", (0, 130), "slot"),
    ("bg_color",     "框的底色",     "框的背景颜色",                  "color", None, "slot"),
    ("bg_alpha",     "底色不透明度",  "0 = 完全不要底色",              "int", (0, 255), "slot"),
    ("border",       "框的描边",     "要不要边框",                    "bool", None, "slot"),
    ("border_color", "描边颜色",     "边框颜色",                     "color", None, "slot"),
    ("border_alpha", "描边不透明度",  "OBS 那条是 12% 的白",           "int", (0, 255), "slot"),
    ("border_width", "描边粗细",     "边框多粗",                     "int", (1, 8), "slot"),

    ("show_icon",    "显示图标",     "这个框要不要图标",               "bool", None, "slot"),
    ("show_value",   "显示数字",     "这个框要不要数量",               "bool", None, "slot"),
    ("show_label",   "显示名称",     "这个框要不要名称",               "bool", None, "slot"),
    ("icon_size",    "图标大小",     "图标多大",                     "int", (12, 90), "slot"),
    ("num_size",     "数字字号",     "数量文字多大",                  "int", (8, 60), "slot"),
    ("num_color",    "数字颜色",     "留空 = 跟随界面主题",            "color_opt", None, "slot"),
    ("num_bold",     "数字加粗",     "加粗更醒目",                    "bool", None, "slot"),
    ("label_size",   "名称字号",     "名称多大",                     "int", (8, 30), "slot"),
    ("label_color",  "名称颜色",     "留空 = 跟随主题的次要文字色",      "color_opt", None, "slot"),
    ("label_text",   "名称文字",     "这一格写什么字（OBS 上带空格）",   "text", None, "slot"),
    ("prefix",       "数字前缀",     "数字前面加什么，比如 ×",          "text", None, "slot"),
]

FIELD_KEYS = tuple(f[0] for f in FIELDS)
# 位置字段：不进设置界面的滑块（靠「编辑布局」里拖动改），但要能存
POS_FIELDS = ("pos_x", "pos_y")
SLOT_FIELDS = tuple(f[0] for f in FIELDS if f[5] == "slot") + POS_FIELDS
GLOBAL_FIELDS = tuple(f[0] for f in FIELDS if f[5] == "all")


# 经典：一直以来的样子
CLASSIC = {
    "layout": "row", "spacing": 8,
    "slot_w": 96, "slot_h": 96, "radius": 12,
    "bg_color": "#141418", "bg_alpha": 150,
    "border": False, "border_color": "#FFFFFF",
    "border_alpha": 30, "border_width": 1,
    "show_icon": True, "show_value": True, "show_label": False,
    "icon_size": 46, "num_size": 17, "num_color": "", "num_bold": True,
    "label_size": 11, "label_color": "", "label_text": "", "prefix": "",
    "pos_x": None, "pos_y": None,
    "overrides": {},
}

# 直播间：**逐字对齐「直播间美化.html」**
#
#   .stats-2x2  { grid; gap:10px; width:340px }
#        → 2×2，间距 10，每格 (340-10)/2 = 165 宽
#   .stat-cell  { background: rgba(20,20,26,.62) }     → #14141A / 158
#               { border:1px solid rgba(255,255,255,.12) } → 白 / 31
#               { border-radius:14px; padding:14px 12px }  → 圆角 14
#   .label      { font-size:13px; color:#c8ccd4; margin-bottom:6px }
#   .value      { font-size:30px; font-weight:800; color:#f0f0f0 }
#   .mora .value      #facc15
#   .artifact .value  #c4b5fd
#   .time .value      #67e8f9 / font-size:22px
#
#   高度 = padding(14+14) + label 13 + 间距 6 + value 30 = 77
#   名称带空格（"摩 拉"），材料/狗粮的数字前面有「×」
BAR_LIVE = {
    "layout": "grid", "spacing": 10,
    "slot_w": 165, "slot_h": 77, "radius": 14,
    "bg_color": "#14141A", "bg_alpha": 158,
    "border": True, "border_color": "#FFFFFF",
    "border_alpha": 31, "border_width": 1,
    "show_icon": False, "show_value": True, "show_label": True,
    "icon_size": 34, "num_size": 30, "num_color": "#F0F0F0", "num_bold": True,
    "label_size": 13, "label_color": "#C8CCD4", "label_text": "", "prefix": "",
    "overrides": {
        "slot1": {"num_color": "#FACC15", "label_text": "摩 拉"},
        "slot2": {"prefix": "×", "label_text": "材 料"},
        "slot3": {"num_color": "#C4B5FD", "prefix": "×", "label_text": "狗 粮"},
        "slot4": {"num_color": "#67E8F9", "num_size": 22, "label_text": "挂机时间"},
    },
}

BUILTIN = {"经典": CLASSIC, "直播间": BAR_LIVE}

DEFAULT_STYLE = "经典"

# 老配置里叫 slot_size（宽高合一），读的时候换算过来
_OLD = {"slot_size": ("slot_w", "slot_h")}


def _fill(st):
    """缺的字段用「经典」补；顺便兼容老字段名、补齐 overrides"""
    st = dict(st or {})
    for old, (a, b) in _OLD.items():
        if st.get(old) is not None and st.get(a) is None:
            st[a] = st[b] = st[old]
    out = dict(CLASSIC)
    for k in FIELD_KEYS:
        if st.get(k) is not None:
            out[k] = st[k]
    if st.get("show_label") is None and st.get("show_label_flag") is not None:
        out["show_label"] = st["show_label_flag"]
    ov = {}
    for key, d in (st.get("overrides") or {}).items():
        if key in SLOT_KEYS and isinstance(d, dict):
            ov[key] = {k: v for k, v in d.items() if k in SLOT_FIELDS}
    out["overrides"] = ov
    return out


def style_for(st, key):
    """某一个框最终生效的样式 = 全局 + 该格的覆盖"""
    out = {k: st.get(k, CLASSIC.get(k)) for k in FIELD_KEYS}
    out["layout"] = st.get("layout", "row")
    out["spacing"] = st.get("spacing", 8)
    for f in POS_FIELDS:                     # 位置默认没有（自动排）
        out[f] = None
    for k, v in ((st.get("overrides") or {}).get(key) or {}).items():
        if k in SLOT_FIELDS and v is not None:
            out[k] = v
    return out


def get_pos(st, key):
    """某一格在「自由摆放」下的位置（没设过就返回 None，由调用方自动排）"""
    ov = (st.get("overrides") or {}).get(key) or {}
    x, y = ov.get("pos_x"), ov.get("pos_y")
    if x is None or y is None:
        return None
    try:
        return int(x), int(y)
    except Exception:
        return None


def set_pos(st, key, x, y):
    """改某一格的位置（直接改传进来的 dict）"""
    ov = dict(st.get("overrides") or {})
    d = dict(ov.get(key) or {})
    d["pos_x"] = int(x)
    d["pos_y"] = int(y)
    ov[key] = d
    st["overrides"] = ov
    return st


def slot_label(st, key):
    """某一格最终显示的名称（逐格设置优先，否则用默认名）"""
    t = str(style_for(st, key).get("label_text") or "").strip()
    return t or SLOT_NAMES.get(key, "")


def slot_prefix(st, key):
    return str(style_for(st, key).get("prefix") or "")


# ---------------- 读写 ----------------

def _read():
    if STYLES_FILE.exists():
        try:
            d = json.loads(STYLES_FILE.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                return d
        except Exception:
            pass
    return {}


def _write(d):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        STYLES_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2),
                               encoding="utf-8")
    except Exception:
        pass


def all_styles():
    d = _read()
    out = {k: dict(v) for k, v in BUILTIN.items()}
    for name, st in (d.get("styles") or {}).items():
        if name not in out:
            out[name] = _fill(st)
    return out


def names():
    return list(all_styles().keys())


def is_builtin(name):
    return name in BUILTIN


def get(name):
    return all_styles().get(name) or dict(CLASSIC)


def current():
    d = _read()
    cur = str(d.get("current") or DEFAULT_STYLE)
    if cur not in all_styles():
        cur = DEFAULT_STYLE
    return cur


def set_current(name):
    d = _read()
    d["current"] = str(name)
    _write(d)


def save_style(name, fields):
    """新建或修改一套**用户样式**（内置的不让改）"""
    if is_builtin(name):
        return False
    d = _read()
    d.setdefault("styles", {})
    d["styles"][name] = _fill(fields)
    _write(d)
    return True


def delete_style(name):
    if is_builtin(name):
        return False
    d = _read()
    st = d.get("styles") or {}
    if name in st:
        del st[name]
        _write(d)
        if str(d.get("current") or "") == name:
            set_current(DEFAULT_STYLE)
        return True
    return False


def rename_style(old, new):
    new = str(new).strip()
    if not new or is_builtin(old) or is_builtin(new) or old == new:
        return False
    d = _read()
    st = d.get("styles") or {}
    if old not in st or new in st:
        return False
    # ⚠ 这里要拿**存进去的** current 判断，不能用 current() ——
    #   改名之后旧名字已经不在名单里，current() 会回退成「经典」，
    #   那就判断不出"改的正是当前用的那套"，当前样式会莫名其妙跳掉。
    was_current = str(d.get("current") or "") == old
    st[new] = st.pop(old)
    d["styles"] = st
    if was_current:
        d["current"] = new
    _write(d)
    return True
