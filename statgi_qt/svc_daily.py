# -*- coding: utf-8 -*-
"""每日收益汇总服务 —— 给「收益记录」页（每日柱状图）用。

数据来自「收益细则」（`data/sessions.json`）。一条记录 = 一段挂机：

    {"start": "2026-10-04 17:21:47", "seconds": 3600,
     "mora": 1234, "artifact": 5, "materials": {"霓裳花": 3, ...}}

按**开始时间的日期**归到那一天，把摩拉 / 狗粮 / 材料个数分别加起来。

⚠ 三条约定（用户 2026-10-04 定的）：
    ① 没有收益的那天**直接跳过**，不画零高柱子；
    ② 跨零点的挂机段算在**开始那天**（跟记账口径一致）；
    ③ 只读，不改任何数据。

为什么单独开一个模块：`svc_records` 的契约是"同签名转发、不改行为"，
往里塞新函数就破坏那个约定了。
"""
from datetime import date, datetime, timedelta

import svc_records


def _rec_date(rec):
    """一条记录属于哪天（"YYYY-MM-DD"）；取不到返回 "" """
    s = str(rec.get("start", "") or "").strip()
    return s[:10] if len(s) >= 10 else ""


def _short(label_date):
    """"2026-10-04" → "10-04"（横轴用）"""
    return label_date[5:] if len(label_date) >= 10 else label_date


def _month_label(key):
    """'2026-10' → '2026年10月'"""
    try:
        y, m = key.split("-")[:2]
        return f"{y}年{int(m)}月"
    except Exception:
        return key


def _accumulate(records, keep):
    """把记录按天累加；keep(日期) 返回 False 就跳过"""
    per_day = {}
    for rec in records:
        d = _rec_date(rec)
        if not d or not keep(d):
            continue
        slot = per_day.setdefault(d, {"mora": 0, "artifact": 0,
                                      "materials": 0, "seconds": 0})
        slot["mora"] += int(rec.get("mora", 0) or 0)
        slot["artifact"] += int(rec.get("artifact", 0) or 0)
        slot["materials"] += sum(
            int(v) for v in (rec.get("materials") or {}).values())
        slot["seconds"] += int(rec.get("seconds", 0) or 0)
    return per_day


def _rows_from(per_day):
    """per_day → 升序的行；**没有收益的那天直接跳过**"""
    rows = []
    for d in sorted(per_day):
        slot = per_day[d]
        if slot["mora"] <= 0 and slot["artifact"] <= 0 and slot["materials"] <= 0:
            continue
        rows.append({"date": d, "label": _short(d), **slot})
    return rows


def _summary(rows):
    n = len(rows)
    return {
        "days": n,
        "mora": sum(r["mora"] for r in rows),
        "artifact": sum(r["artifact"] for r in rows),
        "materials": sum(r["materials"] for r in rows),
        "seconds": sum(r["seconds"] for r in rows),
        "avg_mora": (sum(r["mora"] for r in rows) // n) if n else 0,
        "avg_artifact": (sum(r["artifact"] for r in rows) // n) if n else 0,
        "avg_materials": (sum(r["materials"] for r in rows) // n) if n else 0,
        "peak": max(rows, key=lambda r: r["mora"]) if rows else None,
        "from": rows[0]["date"] if rows else "",
        "to": rows[-1]["date"] if rows else "",
    }


def month_options(limit=36):
    """**有收益的月份**，新的在前 —— 给「收益记录」页的下拉框用。

    用户 2026-10-04 定的：不要"从今天倒数 N 天"，也不要"全部"
    （挂久了全部的数据太多）。所以按自然月看，一个月一屏。

    ⚠ `days` 数的是**有收益的天数**，跟图上柱子数一致 ——
      别把"挂了但没收益"的那天算进去，不然下拉里的天数跟图对不上。
    """
    per_day = _accumulate(svc_records.load_sessions() or [],
                          lambda d: True)
    per_month = {}
    for d in sorted(per_day):
        slot = per_day[d]
        if slot["mora"] <= 0 and slot["artifact"] <= 0 and slot["materials"] <= 0:
            continue
        m = per_month.setdefault(d[:7], {"mora": 0, "artifact": 0,
                                         "materials": 0, "days": 0})
        m["mora"] += slot["mora"]
        m["artifact"] += slot["artifact"]
        m["materials"] += slot["materials"]
        m["days"] += 1

    out = []
    for key in sorted(per_month, reverse=True):
        slot = per_month[key]
        out.append({"key": key, "label": _month_label(key),
                    "mora": slot["mora"], "artifact": slot["artifact"],
                    "materials": slot["materials"], "days": slot["days"]})
    return out[:limit]


def daily_totals(days=None, month=None, today=None):
    """按天汇总。

    month : "2026-10" —— **按自然月**（优先于 days）
    days  : 最近多少天（None / 0 = 不限）
    today : 截止到哪天（"YYYY-MM-DD" 或 date）；默认今天。给测试用 ——
            不然测试结果会随日期变。

    返回 (rows, summary)：rows 升序，只含**有收益**的那几天。
    """
    if today is None:
        end = date.today()
    elif isinstance(today, str):
        end = datetime.strptime(today[:10], "%Y-%m-%d").date()
    else:
        end = today

    start = None
    if not month and days and int(days) > 0:
        start = end - timedelta(days=int(days) - 1)

    if month:
        key = str(month)[:7]
        keep = lambda d: d[:7] == key                      # noqa: E731
    elif start is not None:
        lo, hi = start.isoformat(), end.isoformat()
        keep = lambda d: lo <= d <= hi                     # noqa: E731
    else:
        keep = lambda d: True                              # noqa: E731

    rows = _rows_from(_accumulate(svc_records.load_sessions() or [], keep))
    return rows, _summary(rows)
