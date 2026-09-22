# -*- coding: utf-8 -*-
"""监测悬浮窗的配置模型 —— 动态项目列表 + 整体窗口设置。

设计目标（按需求）：
    · **不是**固定 4 个格子，而是**动态项目列表**，能加能删
    · 每个项目有**独立的**字体 / 卡片 / 内容设置，互不影响
    · 另有**整体窗口设置**（排列方向、间距、内边距、整体背景…）
    · 全部存 JSON，重启自动恢复
    · 结构上支持以后继续加"项目类型"和"新属性"

存哪：``data/bar_items.json``

项目类型（type）：
    number  数值型 —— 程序动态更新数字（摩拉 / 材料数 / 狗粮…）
    time    时间型 —— 程序自动更新（运行时间）
    text    文本型 —— 固定文字（"正在监测"）

数据源（source，只有 number/time 用得上）：
    mora            摩拉
    material_total  材料总数
    artifact        狗粮
    runtime         运行时间
    material:名字    某个具体材料的数量（能盯住一个稀有材料刷了多少）
"""
import copy
import json

from pathlib import Path

import paths

DATA_DIR = paths.app_dir() / "data"
ITEMS_FILE = DATA_DIR / "bar_items.json"
PRESETS_FILE = DATA_DIR / "bar_presets.json"      # 用户自己存的预设

# ---------------- 数据源 ----------------
# (值, 显示名, 说明)
SOURCES = [
    ("mora",            "摩拉",       "当前摩拉数量"),
    ("material_total",  "材料总数",   "所有材料加起来的个数"),
    ("artifact",        "狗粮",       "圣遗物个数"),
    ("runtime",         "运行时间",   "已监测的时长 00:00:00"),
    ("material",        "某个材料",   "盯住一个材料，看它刷了多少（在下面填名字）"),
    ("status",          "监测状态",   "显示当前是否正在监测"),
]
SOURCE_LABEL = {v: n for v, n, _ in SOURCES}
SOURCE_DESC = {v: d for v, _, d in SOURCES}

ALIGNMENTS = [("居中", "center"), ("靠左", "left"), ("靠右", "right")]
ALIGN_QSS = {"center": "center", "left": "left", "right": "right"}

LAYOUTS = [("竖排", "column"), ("横排", "row"),
           ("2×2", "grid"), ("自由摆放", "free")]

# ---------------- 默认配置 ----------------

DEFAULT_WINDOW = {
    "layout": "column",       # column 竖排 / row 横排
    "spacing": 8,             # 项目之间
    "padding": 10,            # 窗口内边距
    "bg_color": "#000000",    # 整体背景
    "bg_alpha": 0,            # 0 = 窗口本身不要背景（只有各个卡片）
    "radius": 14,             # 整体圆角
    "width": 0,               # 0 = 跟着内容自动
    "height": 0,
    "opacity": 1.0,           # 整个窗口的透明度
    "always_on_top": True,
}


def _card(color="#14141A", alpha=158, radius=14, w=165, h=77):
    return {
        "width": w, "height": h,
        "bg_color": color, "bg_alpha": alpha, "radius": radius,
        "border": True, "border_color": "#FFFFFF",
        "border_alpha": 31, "border_width": 1,
        "shadow": False, "padding": 10,
    }


def _fonts(title_size=13, title_color="#C8CCD4",
           value_size=30, value_color="#F0F0F0"):
    return {
        "title_font": "Microsoft YaHei UI", "title_size": title_size,
        "title_bold": False, "title_color": title_color, "title_align": "center",
        "value_font": "Microsoft YaHei UI", "value_size": value_size,
        "value_bold": True, "value_color": value_color, "value_align": "center",
    }


def _item(iid, source, title, **kw):
    d = {
        "id": iid,
        "type": "time" if source == "runtime" else "number",
        "source": source,
        "material": "",           # source == "material" 时用
        "title": title,
        "text": "",
        "prefix": "",
        "suffix": "",
        "show_title": True,
        "show_value": True,
        "show_icon": False,
        "icon": "",               # 图标文件名（icons 目录里）
        "icon_size": 34,
        "pos_x": None,            # 自由摆放时的位置（None = 自动排）
        "pos_y": None,
        "visible": True,
        # ---- 显示选项（都能单独开关）----
        "thousands": True,        # 千分位（143,610）
        "compact": False,         # 大数用「万」（14.4万）
        "hide_zero": False,       # 数值是 0 就不显示这一项
        "show_rate": False,       # 多显示一行「每小时速率」
        "title_below": False,     # 标题放到数值下面
        "icon_pos": "top",        # 图标位置：top / left / right
        "suffix_unit": "",        # 单位后缀（个 / 枚 …），跟 suffix 分开好区分
    }
    d.update(_card())
    d.update(_fonts())
    d.update(kw)
    return d


def default_items():
    """默认 = 「经典」预设（原来那个悬浮窗的样子）"""
    return copy.deepcopy(BUILTIN_PRESETS["经典"]["items"])


# ---------------- 预设 ----------------
# 两套现成的：原来的悬浮窗（图标 + 数字，横排）和 OBS 那条（直播间）

def _classic_items():
    """经典：三个小方卡片，上面图标、下面数字，横排"""
    out = []
    for iid, src, title, icon, color in (
            ("mora", "mora", "摩拉", "_bar_slot1.png", ""),
            ("mat", "material_total", "材料", "_bar_slot2.png", ""),
            ("art", "artifact", "狗粮", "_bar_slot3.png", "")):
        it = _item(iid, src, title,
                   width=96, height=96, radius=12,
                   bg_color="#141418", bg_alpha=150,
                   border=False, padding=8,
                   show_title=False, show_value=True, show_icon=True,
                   icon=icon, icon_size=46, value_size=17,
                   value_color=color or "#F0F0F0")
        out.append(it)
    return out


def _live_items():
    """直播间：照「直播间美化.html」—— 2×2、无图标、显示名称、各格不同颜色"""
    out = []
    for iid, src, title, prefix, color, vsize in (
            ("mora", "mora", "摩 拉", "", "#FACC15", 30),
            ("mat", "material_total", "材 料", "×", "#F0F0F0", 30),
            ("art", "artifact", "狗 粮", "×", "#C4B5FD", 30),
            ("time", "runtime", "挂机时间", "", "#67E8F9", 22)):
        it = _item(iid, src, title,
                   width=165, height=77, radius=14,
                   bg_color="#14141A", bg_alpha=158,
                   border=True, border_color="#FFFFFF", border_alpha=31,
                   border_width=1, padding=12,
                   show_title=True, show_value=True, show_icon=False,
                   prefix=prefix, value_size=vsize, value_color=color,
                   title_size=13, title_color="#C8CCD4")
        out.append(it)
    return out


BUILTIN_PRESETS = {
    "经典": {
        "window": dict(DEFAULT_WINDOW, layout="row", spacing=8, padding=10,
                       bg_alpha=0),
        "items": _classic_items(),
    },
    "直播间": {
        "window": dict(DEFAULT_WINDOW, layout="grid", spacing=10, padding=10,
                       bg_alpha=0),
        "items": _live_items(),
    },
}


def preset_names():
    """内置两套 + 用户自己存的（内置的不能删不能改）"""
    return list(BUILTIN_PRESETS.keys()) + list(user_presets().keys())


def is_builtin_preset(name):
    return name in BUILTIN_PRESETS


def all_presets():
    out = {k: copy.deepcopy(v) for k, v in BUILTIN_PRESETS.items()}
    out.update(user_presets())
    return out


def user_presets():
    if PRESETS_FILE.exists():
        try:
            d = json.loads(PRESETS_FILE.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                return d
        except Exception:
            pass
    return {}


def _write_presets(d):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        PRESETS_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2),
                                encoding="utf-8")
    except Exception:
        pass


def save_preset(name, cfg=None):
    """把当前配置存成一套预设（内置名字不让覆盖）"""
    name = str(name).strip()
    if not name or is_builtin_preset(name):
        return False
    d = user_presets()
    d[name] = cfg or load()
    _write_presets(d)
    return True


def delete_preset(name):
    if is_builtin_preset(name):
        return False
    d = user_presets()
    if name in d:
        del d[name]
        _write_presets(d)
        return True
    return False


def rename_preset(old, new):
    new = str(new).strip()
    if not new or is_builtin_preset(old) or new in all_presets() or old == new:
        return False
    d = user_presets()
    if old not in d:
        return False
    d[new] = d.pop(old)
    _write_presets(d)
    return True


def apply_preset(name):
    """套用一套预设（会盖掉当前配置）"""
    p = all_presets().get(name)
    if not p:
        return load()
    cfg = {"window": dict(p.get("window") or DEFAULT_WINDOW),
           "items": copy.deepcopy(p.get("items") or [])}
    save(cfg)
    return cfg


# ---------------- 读写 ----------------

def default_config():
    """默认配置 = 套用「经典」预设（原来那个悬浮窗的样子）"""
    p = BUILTIN_PRESETS["经典"]
    return {"window": dict(p["window"]),
            "items": copy.deepcopy(p["items"])}


def _fill_item(d):
    """补全一项缺的字段（老配置文件也能用）"""
    base = _item(str(d.get("id") or "item"), str(d.get("source") or "mora"), "")
    out = dict(base)
    out.update({k: v for k, v in (d or {}).items() if v is not None})
    return out


def load():
    """读配置；没有 / 坏了就用默认"""
    if ITEMS_FILE.exists():
        try:
            raw = json.loads(ITEMS_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("items"), list) \
                    and raw["items"]:
                win = dict(DEFAULT_WINDOW)
                win.update({k: v for k, v in (raw.get("window") or {}).items()
                            if v is not None})
                return {"window": win,
                        "items": [_fill_item(x) for x in raw["items"]]}
        except Exception:
            pass
    return default_config()


def save(cfg):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        ITEMS_FILE.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def reset():
    cfg = default_config()
    save(cfg)
    return cfg


def new_item(kind="number"):
    """新建一项（id 保证不重复）"""
    cfg = load()
    used = {str(x.get("id")) for x in cfg["items"]}
    i = len(used) + 1
    while f"item{i}" in used:
        i += 1
    src = {"number": "material_total", "time": "runtime",
           "status": "status"}[kind]
    it = _item(f"item{i}", src, "新项目")
    it["type"] = kind
    if kind == "text":
        it["show_value"] = True
    return it


# ---------------- 取值 ----------------

def _num(n, item):
    """按显示选项把数字格式化成文字（千分位 / 万 / 带单位）"""
    try:
        n = int(n)
    except Exception:
        n = 0
    if item.get("compact"):
        if abs(n) >= 10000:
            s = f"{n / 10000:.1f}".rstrip("0").rstrip(".")
            return f"{s}万"
        return str(n)
    if item.get("thousands"):
        return f"{n:,}"
    return str(n)


def format_value(item, snap):
    """按项目配置把当前数据算成要显示的文字。

    snap = state.snapshot() 的结果：
        {"mora": int, "artifact": int, "seconds": int, "materials": {名: 数}}
    """
    src = str(item.get("source") or "mora")
    if src == "status":
        return "正在监测" if snap.get("monitoring") else "已停止"
    if src == "mora":
        return _num(snap.get("mora", 0), item)
    if src == "artifact":
        return _num(snap.get("artifact", 0), item)
    if src == "runtime":
        sec = max(0, int(snap.get("seconds", 0)))
        return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"
    if src == "material_total":
        mats = snap.get("materials") or {}
        return _num(sum(int(v) for v in mats.values()), item)
    if src == "material":
        name = str(item.get("material") or "")
        mats = snap.get("materials") or {}
        return _num(mats.get(name, 0), item)
    return "0"


def raw_number(item, snap):
    """这一项对应的原始数字（算速率用）；时间/文字型返回 None"""
    src = str(item.get("source") or "mora")
    if src in ("runtime", "status"):
        return None
    if src == "mora":
        return int(snap.get("mora", 0))
    if src == "artifact":
        return int(snap.get("artifact", 0))
    if src == "material_total":
        return sum(int(v) for v in (snap.get("materials") or {}).values())
    if src == "material":
        return int((snap.get("materials") or {}).get(
            str(item.get("material") or ""), 0))
    return None


def format_rate(item, snap):
    """每小时速率（要开了 show_rate 才用）"""
    n = raw_number(item, snap)
    sec = max(1, int(snap.get("seconds", 0)))
    if n is None or sec < 60:
        return "—"
    per_h = n * 3600.0 / sec
    return f"{_num(round(per_h), item)}/时"


def full_text(item, snap):
    """前缀 + 数值 + 后缀"""
    v = format_value(item, snap)
    if not v:
        return ""
    return f"{item.get('prefix') or ''}{v}{item.get('suffix') or ''}"


def should_hide(item, snap):
    """hide_zero：数值是 0 就把整项藏起来（时间型不管）"""
    if not item.get("hide_zero"):
        return False
    n = raw_number(item, snap)
    return n == 0
