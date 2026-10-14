# -*- coding: utf-8 -*-
"""一键备份 / 一键恢复（v0.9.7 第一批）。

用户要的效果（大白话）：
    · 备份：把「设置 + 收益记录 + 材料名单 + 收藏夹 + 悬浮窗样式」
            打包成**一个文件**，文件名带日期。
    · 恢复：选一个备份文件 → **先把现在的数据自动另存一份**（防手滑）→ 再导入。

放进备份的东西（**不含**日志、缓存、图片 —— 那些要么没用要么很大）：
    config/settings.json          设置
    data/history.json             收益记录
    data/sessions.json            监测会话
    data/today.json               今天的数
    data/names.json               材料名单（含用户纠正过的）
    data/materials.json           材料表
    data/favorites.json           收藏夹
    data/bar_items.json           悬浮窗条目
    data/bar_presets.json         悬浮窗预设
    data/bar_styles.json          悬浮窗样式

为什么不做"加密"：用户明确说过要简单、能自己打开看 ✓
"""
import json
import shutil
import time
import zipfile
from pathlib import Path

import paths

# 相对路径（相对程序目录）—— 备份文件里就按这个结构放
CONFIG_REL = "config/settings.json"
DATA_FILES = (
    "data/history.json",
    "data/sessions.json",
    "data/today.json",
    "data/names.json",
    "data/materials.json",
    "data/favorites.json",
    "data/bar_items.json",
    "data/bar_presets.json",
    "data/bar_styles.json",
)
MANIFEST = "StatGI备份说明.json"          # 放在包里，恢复时会先看它
KIND = "statgi-backup"
FORMAT = 1


def _root():
    return Path(paths.app_dir())


def default_name():
    """默认文件名：StatGI备份_2026-10-14_2215.zip"""
    return "StatGI备份_" + time.strftime("%Y-%m-%d_%H%M") + ".zip"


def _files():
    """要打包的文件（只收真实存在的）"""
    root = _root()
    out = []
    for rel in (CONFIG_REL,) + DATA_FILES:
        f = root / rel
        if f.is_file():
            out.append((rel, f))
    return out


def preview(zip_path=None):
    """给界面用：备份/恢复之前让用户看一眼"会动到哪些东西"。

    返回 {"files": [(名字, 大小)], "time": ..., "version": ...}
    · 不传 zip_path → 说的是"备份会包含什么"
    · 传了 zip_path → 说的是"这个备份文件里有什么"
    """
    if zip_path is None:
        items = [(rel, f.stat().st_size) for rel, f in _files()]
        return {"files": items, "time": time.strftime("%Y-%m-%d %H:%M"),
                "version": "", "source": "本机现在"}
    try:
        with zipfile.ZipFile(zip_path) as z:
            man = {}
            if MANIFEST in z.namelist():
                man = json.loads(z.read(MANIFEST).decode("utf-8"))
            items = [(n, z.getinfo(n).file_size) for n in z.namelist()
                     if n != MANIFEST and not n.endswith("/")]
            return {"files": items, "time": man.get("time", "?"),
                    "version": man.get("version", "?"), "source": "备份文件"}
    except Exception as e:
        return {"files": [], "time": "", "version": "",
                "error": f"{type(e).__name__}: {e}"}


def make(zip_path, version=""):
    """做备份。返回 (成功?, 说明文字)"""
    zip_path = Path(zip_path)
    files = _files()
    if not files:
        return False, "本机没有任何可备份的数据（可能还没用过程序）"
    try:
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for rel, f in files:
                z.write(f, rel)
            z.writestr(MANIFEST, json.dumps({
                "kind": KIND, "format": FORMAT, "version": str(version),
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "count": len(files),
                "note": "这是 StatGI 的备份文件。恢复时程序会先把你现在的数据另存一份。",
            }, ensure_ascii=False, indent=2))
    except Exception as e:
        return False, f"备份失败：{type(e).__name__}: {e}"
    kb = zip_path.stat().st_size / 1024
    return True, (f"备份完成：{zip_path.name}\n"
                  f"共 {len(files)} 个文件，{kb:.0f} KB")


def check(zip_path):
    """恢复之前先验一下这个文件像不像我们的备份。返回 (可以?, 说明)"""
    p = Path(zip_path)
    if not p.is_file():
        return False, "文件不存在"
    try:
        with zipfile.ZipFile(p) as z:
            names = z.namelist()
            if MANIFEST not in names:
                return False, ("这个文件里没有 StatGI 的备份说明，"
                               "可能不是本程序做的备份。")
            man = json.loads(z.read(MANIFEST).decode("utf-8"))
            if man.get("kind") != KIND:
                return False, "备份说明里的类型不对，可能不是本程序的备份。"
            got = [n for n in names if n in (CONFIG_REL,) + DATA_FILES]
            if not got:
                return False, "这个备份里没有任何数据文件。"
            return True, (f"这是一份 {man.get('time', '?')} 的备份"
                          f"（版本 {man.get('version') or '未知'}），"
                          f"里面有 {len(got)} 个数据文件。")
    except Exception as e:
        return False, f"打不开这个文件：{type(e).__name__}: {e}"


def restore(zip_path):
    """恢复。会先把现在的数据另存到 备份/恢复前_时间戳/。

    返回 (成功?, 说明文字)
    """
    ok, why = check(zip_path)
    if not ok:
        return False, why
    root = _root()
    stamp = time.strftime("%Y%m%d_%H%M%S")
    safety = root / "备份" / ("恢复前_" + stamp)
    moved = []
    try:
        with zipfile.ZipFile(zip_path) as z:
            names = set(z.namelist())
            # ① 先把"现在有、且这次会被覆盖"的文件挪到安全目录
            for rel, f in _files():
                if rel in names:
                    dst = safety / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, dst)
                    moved.append(rel)
            # ② 再把备份里的写回去
            for rel in (CONFIG_REL,) + DATA_FILES:
                if rel in names:
                    dst = root / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(rel) as src, open(dst, "wb") as out:
                        shutil.copyfileobj(src, out)
    except Exception as e:
        return False, f"恢复失败：{type(e).__name__}: {e}"
    msg = f"恢复完成：写回 {len([r for r in (CONFIG_REL,) + DATA_FILES if r in names])} 个文件"
    if moved:
        msg += f"\n（恢复前的旧数据已另存到：备份\\{safety.name}）"
    return True, msg
