# -*- coding: utf-8 -*-
"""监测记录（收益记录）

每次「开始监测 → 停止监测」算一条记录，记录这一段时间内的收益：
- 开始时间 / 结束时间 / 时长
- 获得摩拉、狗粮（圣遗物）
- 获得的材料明细

数据文件：data/sessions.json（一个数组，按时间先后排列）
"""
import json

import paths


def _file():
    return paths.app_dir() / "data" / "sessions.json"


def load_sessions():
    """读取全部记录（读不到就返回空列表）"""
    p = _file()
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return []


def save_sessions(items):
    p = _file()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def add_session(record):
    """追加一条记录，返回更新后的列表"""
    items = load_sessions()
    items.append(record)
    save_sessions(items)
    return items


def clear_sessions():
    """清空所有记录"""
    save_sessions([])


def make_record(start_ts, end_ts, seconds, mora, artifact, materials):
    """构造一条记录（时间用本地时间字符串，方便显示）"""
    import time as _t
    return {
        "start": _t.strftime("%Y-%m-%d %H:%M:%S", _t.localtime(start_ts)),
        "end": _t.strftime("%Y-%m-%d %H:%M:%S", _t.localtime(end_ts)),
        "seconds": int(max(0, seconds)),
        "mora": int(max(0, mora)),
        "artifact": int(max(0, artifact)),
        "materials": {str(k): int(v) for k, v in (materials or {}).items() if v},
    }
