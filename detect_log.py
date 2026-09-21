# -*- coding: utf-8 -*-
"""识别日志 —— 每统计到一笔就记一条，方便事后查"哪次判断错了"。

为什么要它：
    光看收益记录只能看到"某材料一共 3238 个"，查不出是什么时候、被什么
    文字骗了。有了这个日志就能看到每一笔的时间 + 原始 OCR 文字。

文件：``data/识别日志.log``（UTF-8，记事本直接看）

格式：
    ============================================================
    2026-09-22 02:40:00  启动 StatGI
    识别名单：材料 574 个　圣遗物 299 个
    名单内容：不祥的面具, 破损的面具, 牢固的箭簇, ...
    ============================================================
    2026-09-22 02:41:03  材料  地脉的旧枝 ×1   ← "地脉的旧枝×1"   行队列
    ────────────────┬──  ──┬─  ─────┬────  ──────  ────┬────  ────┬───
                  时间   类型      统计结果   原始OCR文字   来源

满了怎么办：
    超过 MAX_BYTES（10 MB）就**把最早的部分删掉**，只留最近的 KEEP_BYTES，
    给新日志腾地方。挂在硬盘上不会无限涨。
"""
import os
import time

from pathlib import Path

import paths

DATA_DIR = paths.app_dir() / "data"
LOG_FILE = DATA_DIR / "识别日志.log"

# 超过 10 MB 就清理：只保留最近的 4 MB
MAX_BYTES = 10 * 1024 * 1024
KEEP_BYTES = 4 * 1024 * 1024

# 名单那一长串折成多少字一行
WRAP = 88

_quiet = False


def enabled(settings) -> bool:
    """用户可以关掉（挂机很久的话日志会有点大）"""
    try:
        return bool(settings.get("log_detections", True))
    except Exception:
        return True


# ---------------- 写盘 ----------------

def _write(line):
    global _quiet
    if _quiet:
        return
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > MAX_BYTES:
            _trim()
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        _quiet = True          # 磁盘满/没权限之类，静默停掉，别影响识别


def _trim():
    """把最早的部分删掉，只留最近的 KEEP_BYTES。"""
    try:
        raw = LOG_FILE.read_bytes()
        if len(raw) <= KEEP_BYTES:
            return
        cut = raw[-KEEP_BYTES:]
        # 从换行处切开，别把一行截成半截
        nl = cut.find(b"\n")
        if nl >= 0:
            cut = cut[nl + 1:]
        with open(LOG_FILE, "wb") as f:
            f.write("...\n（更早的日志已自动清理）\n".encode("utf-8") + cut)
    except Exception:
        pass


# ---------------- 会话标记 ----------------

def session_start(settings=None, app_name="StatGI"):
    """启动时写一段抬头：时间 + **当前识别名单**。

    为什么要把名单写进去：出了"某材料认不出来"的问题时，
    得先知道当时用的是哪份名单（用户改过没有）。
    """
    if settings is not None and not enabled(settings):
        return
    try:
        import names_db
        d = names_db.load()
        mats, arts = d["materials"], d["artifacts"]
    except Exception:
        mats, arts = [], []

    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    bar = "=" * 64
    lines = [bar, f"{ts}  启动 {app_name}"]
    if mats or arts:
        lines.append(f"识别名单：材料 {len(mats)} 个　圣遗物 {len(arts)} 个")
        allnames = "、".join(mats + arts)
        for i in range(0, len(allnames), WRAP):
            head = "名单内容：" if i == 0 else "　　　　　"
            lines.append(head + allnames[i:i + WRAP])
    else:
        lines.append("识别名单：**空的**（什么都识别不到）")
    lines.append(bar)
    _write("\n".join(lines))


def session_end(settings=None, app_name="StatGI"):
    """关闭时写一行"""
    if settings is not None and not enabled(settings):
        return
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    _write(f"{ts}  关闭 {app_name}")


# ---------------- 每笔 ----------------

def log_event(kind, name, count=1, amount=0, raw="", source="", settings=None):
    """记一条。

    kind:   "材料" / "摩拉" / "狗粮" / "未登记"
    name:   材料名（摩拉/狗粮可空）
    count:  个数
    amount: 摩拉金额
    raw:    原始 OCR 文字（最能说明问题的一列）
    source: "行队列" / "区域扫描" / "不在名单里"
    """
    if settings is not None and not enabled(settings):
        return
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    if kind == "摩拉":
        what = f"摩拉 +{amount}"
    elif kind == "狗粮":
        what = "狗粮 +1"
    else:
        what = f"{name} ×{count}"
    line = f"{ts}  {kind}  {what}"
    if raw:
        line += f'\t← "{raw}"'
    if source:
        line += f"\t{source}"
    _write(line)
