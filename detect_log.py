# -*- coding: utf-8 -*-
"""识别日志 —— **每次运行单独一个文件**，放在 `data/识别日志/` 文件夹里。

为什么要分文件（2026-09-29 改的）：
    以前所有记录都往 `data/识别日志.log` 一个文件里追加，越写越大（实机跑几天
    就两万多行）。想查"**某一次**识别是怎么错的"，得在几万行里翻，还要自己
    找"哪儿是这次启动"。现在**每启动一次软件就新开一个文件**（文件名带启动
    时间），一次运行就是完整的一份，按时间挑文件就行。

满了怎么办：
    整个文件夹**超过 20 MB** 就从**最老的**开始删，一直删到 16 MB 以下为止；
    **正在写的那个文件永远不删**。检查时机是每次启动（`session_start`）。
    另外万一某一次跑了很久、单个文件自己就超 20 MB，会把这个文件**原地瘦身**
    （只留最近的一段），不至于无限涨。

文件长这样：
    data/识别日志/识别日志_20260929_040512.log     ← UTF-8，记事本直接看
    data/识别日志/识别日志_20260929_183001.log

内容格式（跟以前一样）：

    ============================================================
    2026-09-22 02:40:00  启动 StatGI
    识别名单：材料 574 个　圣遗物 299 个
    名单内容：不祥的面具, 破损的面具, 牢固的箭簇, ...
    ============================================================
    2026-09-22 02:41:03  材料  地脉的旧枝 ×1   ← "地脉的旧枝×1"   行队列
    ────────────────┬──  ──┬─  ─────┬────  ──────  ────┬────  ────┬───
                   时间   类型      统计结果   原始OCR文字   来源

⚠ 以前那个 `data/识别日志.log` **不删**（那是用户的东西），留着就是了。
"""
import time

from pathlib import Path

import paths

DATA_DIR = paths.app_dir() / "data"
# ★ 文件夹（不是单个文件了）
LOG_DIR = DATA_DIR / "日志" / "识别"

# 文件夹整体超过 20 MB 就清：删到 16 MB 以下（留点余量，别每启动一次都删）
MAX_TOTAL_BYTES = 20 * 1024 * 1024
KEEP_TOTAL_BYTES = 16 * 1024 * 1024

# 名单那一长串折成多少字一行
WRAP = 88

_quiet = False
_current = None          # 本次运行正在写的文件（Path 或 None）


def enabled(settings) -> bool:
    """用户可以关掉（挂机很久的话日志会有点大）"""
    try:
        return bool(settings.get("log_detections", True))
    except Exception:
        return True


# ---------------- 本次运行的文件 ----------------

def current_file():
    """这次运行正在写的那个文件（还没写过就是 None）—— 测试/排查用"""
    return _current


def reset_session():
    """忘掉当前文件（下次写会另开一个）—— 主要给测试用"""
    global _current, _quiet
    _current = None
    _quiet = False


def _open_session():
    """挑一个文件给这次运行（挑过就复用）。

    文件名用启动时刻：`识别日志_20260929_040512.log`。
    ⚠ 用下划线不用冒号 —— Windows 文件名不许带 `:`。
    """
    global _current
    if _current is not None:
        return _current
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        p = LOG_DIR / f"识别日志_{stamp}.log"
        n = 1
        while p.exists():          # 同一秒内开了两次（测试里很常见）
            p = LOG_DIR / f"识别日志_{stamp}_{n}.log"
            n += 1
        _current = p
    except Exception:
        _current = None
    return _current


# ---------------- 写盘 ----------------

def _write(line):
    global _quiet
    if _quiet:
        return
    p = _open_session()
    if p is None:
        return
    try:
        with open(p, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        # 单次运行跑太久、这个文件自己超了上限 → 原地瘦身
        if p.exists() and p.stat().st_size > MAX_TOTAL_BYTES:
            _trim(p)
    except Exception:
        _quiet = True          # 磁盘满/没权限之类，静默停掉，别影响识别


def _trim(p):
    """把**单个文件**最早的部分删掉，只留最近的 KEEP_TOTAL_BYTES。"""
    try:
        raw = p.read_bytes()
        if len(raw) <= KEEP_TOTAL_BYTES:
            return
        cut = raw[-KEEP_TOTAL_BYTES:]
        nl = cut.find(b"\n")       # 从换行处切开，别把一行截成半截
        if nl >= 0:
            cut = cut[nl + 1:]
        with open(p, "wb") as f:
            f.write("...\n（更早的日志已自动清理）\n".encode("utf-8") + cut)
    except Exception:
        pass


# ---------------- 文件夹瘦身 ----------------

def prune():
    """文件夹超过 20 MB → 从最老的开始删，删到 16 MB 以下。

    返回删掉的文件数（测试和排查用）。**当前正在写的文件永不删**。
    """
    try:
        files = sorted((p for p in LOG_DIR.glob("*.log") if p.is_file()),
                       key=lambda q: q.stat().st_mtime)
    except Exception:
        return 0

    def total():
        s = 0
        for p in files:
            try:
                s += p.stat().st_size
            except Exception:
                pass
        return s

    size = total()
    if size <= MAX_TOTAL_BYTES:
        return 0

    removed = 0
    for p in files:                      # 老的在前面
        if size <= KEEP_TOTAL_BYTES:
            break
        if p == _current:
            continue                     # 正在写的那个不删
        try:
            n = p.stat().st_size
            p.unlink()
            size -= n
            removed += 1
        except Exception:
            pass
    return removed


# ---------------- 会话标记 ----------------

def session_start(settings=None, app_name="StatGI"):
    """启动时：**新开一个文件**，写一段抬头（时间 + 当前识别名单），再清旧文件。

    为什么要把名单写进去：出了"某材料认不出来"的问题时，
    得先知道当时用的是哪份名单（用户改过没有）。
    """
    if settings is not None and not enabled(settings):
        return None
    _open_session()
    if _current is None:
        return None

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

    prune()                # 顺手把太老的清理掉
    return _current


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
    source: "行队列" / "区域扫描" / "不在名单里" / "未统计（超过单次上限 N）"
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
