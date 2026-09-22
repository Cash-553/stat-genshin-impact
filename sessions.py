# -*- coding: utf-8 -*-
"""监测记录（收益记录）+ 收藏夹

每次「开始监测 → 停止监测」算一条记录，记录这一段时间内的收益：
- 开始时间 / 结束时间 / 时长
- 获得摩拉、狗粮（圣遗物）
- 获得的材料明细

数据文件：
- data/sessions.json   一个数组，按时间先后排列
- data/favorites.json  收藏夹。**存的是整条记录的副本**，
                       所以原记录被删掉之后，收藏夹里那份还在。
"""
import json
import uuid

import paths


def _file():
    return paths.app_dir() / "data" / "sessions.json"


def _fav_file():
    return paths.app_dir() / "data" / "favorites.json"


def _load(path, default=None):
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return [] if default is None else default


def _save(path, items):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(items, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------- 记录

def load_sessions():
    """读取全部记录（读不到就返回空列表）"""
    return _load(_file())


def save_sessions(items):
    _save(_file(), items)


def add_session(record):
    """追加一条记录，返回更新后的列表"""
    items = load_sessions()
    items.append(record)
    save_sessions(items)
    return items


def clear_sessions():
    """清空所有记录（**不动收藏夹**）"""
    save_sessions([])


def new_id():
    return uuid.uuid4().hex[:12]


def record_key(rec):
    """记录的稳定标识。

    老记录里没有 id，就用「开始|结束」当键 —— 同一秒不可能开两次监测，
    所以够用，而且不会因为列表顺序变了而认错人。
    """
    if not isinstance(rec, dict):
        return ""
    return str(rec.get("id") or f"{rec.get('start','')}|{rec.get('end','')}")


def make_record(start_ts, end_ts, seconds, mora, artifact, materials):
    """构造一条记录（时间用本地时间字符串，方便显示）

    ``name`` / ``notes`` 留空表示「用默认名 / 没有备注」——
    名称默认是「日期 + 开始 → 结束 + 时长」，由 :func:`display_name` 现算，
    用户改过就存进 ``name``。
    """
    import time as _t
    return {
        "id": new_id(),
        "start": _t.strftime("%Y-%m-%d %H:%M:%S", _t.localtime(start_ts)),
        "end": _t.strftime("%Y-%m-%d %H:%M:%S", _t.localtime(end_ts)),
        "seconds": int(max(0, seconds)),
        "mora": int(max(0, mora)),
        "artifact": int(max(0, artifact)),
        "materials": {str(k): int(v) for k, v in (materials or {}).items() if v},
        "name": "",        # 用户改过的名字（空 = 用默认名）
        "notes": "",       # 备注
    }


# ---------------------------------------------------------------- 名称 / 备注

def _dur_text(seconds):
    """时长文字：1小时23分 / 23分05秒 / 45秒"""
    try:
        sec = max(0, int(seconds))
    except Exception:
        sec = 0
    h, m, s = sec // 3600, sec % 3600 // 60, sec % 60
    if h:
        return f"{h}小时{m:02d}分"
    if m:
        return f"{m}分{s:02d}秒"
    return f"{s}秒"


def default_name(rec):
    """默认名称：日期 + 开始 → 结束 + 时长（用户要求的格式）"""
    if not isinstance(rec, dict):
        return ""
    start = str(rec.get("start", "") or "").strip()
    end = str(rec.get("end", "") or "").strip()
    if not start and not end:
        return "未命名记录"
    date, t1 = (start.split(" ", 1) + [""])[:2] if start else ("", "")
    t2 = end.split(" ", 1)[1] if " " in end else ""
    parts = [date or "——"]
    if t1:
        parts.append(t1 + (f" → {t2}" if t2 else ""))
    parts.append(f"时长 {_dur_text(rec.get('seconds', 0))}")
    return "　".join(parts)


def display_name(rec):
    """界面上显示的名称：用户改过就用他的，否则用默认名"""
    if not isinstance(rec, dict):
        return ""
    return str(rec.get("name") or "").strip() or default_name(rec)


def display_notes(rec):
    if not isinstance(rec, dict):
        return ""
    return str(rec.get("notes") or "").strip()


def update_record(rec, **fields):
    """改一条记录的字段（名称 / 备注）。

    ⚠ 原记录和**收藏夹里的副本**都要改 —— 收藏夹存的是整条记录的深拷贝，
    只改一边的话：从收益记录里改名，收藏夹里那条还是老名字。
    """
    if not isinstance(rec, dict):
        return False
    key = record_key(rec)
    changed = False

    items = load_sessions()
    for r in items:
        if record_key(r) == key:
            r.update(fields)
            changed = True
    if changed:
        save_sessions(items)

    favs = load_favorites()
    fav_changed = False
    for f in favs:
        if record_key(f) == key:
            f.update(fields)
            fav_changed = True
    if fav_changed:
        save_favorites(favs)

    rec.update(fields)          # 让调用方手上那份也同步
    return changed or fav_changed


def format_duration(seconds):
    """给界面用的时长显示（跟 _dur_text 同义，对外留个正经名字）"""
    return _dur_text(seconds)


# ---------------------------------------------------------------- 收藏夹

def load_favorites():
    """读取收藏夹（里面是记录的完整副本）"""
    return _load(_fav_file())


def save_favorites(items):
    _save(_fav_file(), items)


def favorite_ids():
    """收藏夹里所有记录的 key 集合"""
    return {record_key(r) for r in load_favorites()}


def is_favorite(rec, ids=None):
    ids = favorite_ids() if ids is None else ids
    return record_key(rec) in ids


def add_favorite(rec):
    """把一条记录**复制**进收藏夹。

    存副本是有意的：这样原记录之后被删掉/清空，收藏夹里那份还在。
    重复收藏不会存两份。
    """
    import time as _t
    favs = load_favorites()
    key = record_key(rec)
    if any(record_key(f) == key for f in favs):
        return favs
    copy = json.loads(json.dumps(rec, ensure_ascii=False))   # 深拷贝
    copy["favorited_at"] = _t.strftime("%Y-%m-%d %H:%M:%S")
    favs.append(copy)
    save_favorites(favs)
    return favs


def remove_favorite(rec_or_key):
    """从收藏夹里移除（传记录或 key 都行）"""
    key = (record_key(rec_or_key)
           if isinstance(rec_or_key, dict) else str(rec_or_key))
    favs = [f for f in load_favorites() if record_key(f) != key]
    save_favorites(favs)
    return favs


def clear_favorites():
    save_favorites([])

