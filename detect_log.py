# -*- coding: utf-8 -*-
"""识别日志 —— 每统计到一笔就记一条，方便事后查"哪次判断错了"。

为什么要它：
    光看收益记录只能看到"某材料一共 3238 个"，查不出是什么时候、被什么
    文字骗了。有了这个日志就能看到每一笔的时间 + 原始 OCR 文字。

文件：``data/识别日志.log``（UTF-8，记事本直接看）

格式：
    2026-09-21 10:15:03  材料  地脉的旧枝 ×1        ← "地脉的旧枝×1"   自动窗口
    ────────────────┬──  ──┬─  ─────┬────  ──────  ────┬────  ────┬───
                  时间   类型      统计结果   原始OCR文字   来源

轮转：超过 MAX_BYTES 就备份成 ``识别日志.1.log``，只留最近一份备份
      （挂机十几个小时也就几百 KB，不会涨太快）
"""
import os
import time

from pathlib import Path

import paths

DATA_DIR = paths.app_dir() / "data"
LOG_FILE = DATA_DIR / "识别日志.log"
BAK_FILE = DATA_DIR / "识别日志.1.log"

# 超过这个大小就轮转一次（5 MB）
MAX_BYTES = 5 * 1024 * 1024

# 写日志失败时不要反复报错刷屏
_quiet = False


def enabled(settings) -> bool:
    """用户可以关掉（挂机很久的话日志会有点大）"""
    try:
        return bool(settings.get("log_detections", True))
    except Exception:
        return True


def log_event(kind, name, count=1, amount=0, raw="", source="", settings=None):
    """记一条。

    kind:   "材料" / "摩拉" / "狗粮"
    name:   材料名（摩拉/狗粮可空）
    count:  个数
    amount: 摩拉金额
    raw:    原始 OCR 文字（最能说明问题的一列）
    source: "自动窗口" / "手动区域" / "行队列"
    """
    global _quiet
    if _quiet:
        return
    if settings is not None and not enabled(settings):
        return
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > MAX_BYTES:
            try:
                if BAK_FILE.exists():
                    BAK_FILE.unlink()
                LOG_FILE.rename(BAK_FILE)
            except Exception:
                pass
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        if kind == "摩拉":
            what = f"摩拉 +{amount}"
        elif kind == "狗粮":
            what = f"狗粮 +1"
        else:
            what = f"{name} ×{count}"
        line = f"{ts}  {kind}  {what}"
        if raw:
            line += f'\t← "{raw}"'
        if source:
            line += f"\t{source}"
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        _quiet = True          # 磁盘满了/没权限之类，静默停掉，别影响识别
