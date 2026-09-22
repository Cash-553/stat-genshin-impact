# -*- coding: utf-8 -*-
"""黑名单 / 白名单 —— 决定「识别到了要不要记账」。

跟 ``names_db``（决定**能不能识别**）是两件事：

    names_db   名单里没有的名字 -> 根本认不出来
    filters_db 名单决定「认出来了要不要算收益」

存哪：设置文件里的 ``records.filters``（跟着 settings.json 走，
不用单独一个文件，也不用管老用户迁移）。

结构::

    {
      "material_white": {"enabled": False, "names": []},
      "material_black": {"enabled": False, "names": []},
      "artifact_white": {"enabled": False, "names": []},
      "artifact_black": {"enabled": False, "names": []},
    }

生效规则（白名单优先）::

    白名单 enabled 且非空 -> 只记白名单里的
    黑名单 enabled         -> 名单里的一律不记

⚠ 白名单 enabled 但**为空** = 什么都不记。这种情况由设置页在离开时
弹窗提醒（见 qt_pages 的 _warn_empty_filters），并自动关掉该白名单。
"""
import copy

# 四张名单：(键, 类别, 显示名)
# 类别 = material / artifact，决定它管的是材料还是圣遗物
LISTS = [
    ("material_white", "material", "材料白名单"),
    ("material_black", "material", "材料黑名单"),
    ("artifact_white", "artifact", "圣遗物白名单"),
    ("artifact_black", "artifact", "圣遗物黑名单"),
]

KEY_LABEL = {k: lab for k, _c, lab in LISTS}
KEY_KIND = {k: c for k, c, _lab in LISTS}

# 默认值（config_manager.DEFAULT_SETTINGS 里也放一份，保持一致）
DEFAULT_FILTERS = {
    k: {"enabled": False, "names": []} for k, _c, _lab in LISTS
}


def defaults():
    return copy.deepcopy(DEFAULT_FILTERS)


def normalize(raw):
    """把外部读来的数据规整成完整结构（缺字段就补默认）"""
    out = defaults()
    if not isinstance(raw, dict):
        return out
    for key, _kind, _lab in LISTS:
        v = raw.get(key)
        if not isinstance(v, dict):
            continue
        out[key]["enabled"] = bool(v.get("enabled", False))
        names = v.get("names")
        if isinstance(names, list):
            out[key]["names"] = [str(x) for x in names if str(x).strip()]
    return out


def get(settings):
    """从 settings 里取出四张名单（已规整）"""
    rec = (settings or {}).get("records")
    raw = (rec or {}).get("filters") if isinstance(rec, dict) else None
    return normalize(raw)


def names_of(settings, key):
    return get(settings).get(key, {}).get("names", [])


def is_enabled(settings, key):
    return bool(get(settings).get(key, {}).get("enabled", False))


# ------------------------------------------------------------
#  识别时调用：认出来了要不要记账
# ------------------------------------------------------------

def allows(settings, kind, name=""):
    """这个物品要不要算进收益。

    kind = "material" / "artifact"
    name = 材料名（圣遗物多半没名字，传空串即可）
    """
    f = get(settings)
    nm = str(name or "")

    white = f.get(f"{kind}_white") or {}
    black = f.get(f"{kind}_black") or {}

    # 白名单优先：只记白名单里的
    if white.get("enabled"):
        wnames = white.get("names") or []
        if not nm:
            return False          # 没名字可对 -> 白名单模式下不记
        return nm in set(wnames)

    # 黑名单：名单里的一律不记
    if black.get("enabled") and nm:
        if nm in set(black.get("names") or []):
            return False

    return True


def empty_enabled_whitelists(settings):
    """返回「开着但空着」的白名单键列表（要弹窗提醒 + 自动关掉）"""
    f = get(settings)
    out = []
    for key, _kind, _lab in LISTS:
        if not key.endswith("_white"):
            continue
        v = f.get(key) or {}
        if v.get("enabled") and not (v.get("names") or []):
            out.append(key)
    return out


def empty_enabled_blacklists(settings):
    """返回「开着但空着」的黑名单键列表（只提醒，不影响识别）"""
    f = get(settings)
    out = []
    for key, _kind, _lab in LISTS:
        if not key.endswith("_black"):
            continue
        v = f.get(key) or {}
        if v.get("enabled") and not (v.get("names") or []):
            out.append(key)
    return out
