# -*- coding: utf-8 -*-
"""维护类服务：识别日志信息 / 清空日志 / 诊断打包 / 设置导出导入。

为什么单独一个模块：UI（设置页）不该直接去翻文件、拼 zip，也不该 import
`detect_log` / `paths` 那一层。所有"翻文件、写文件"的活儿都收在这里，
设置页只调这几个函数。

四件事：
    log_stats()           本次日志多少行、文件夹一共几个文件多大
    clear_logs()          清空识别日志（回收站不经过，直接删）
    collect_diagnose()    把"出问题时要看的东西"打包成一个 zip
    export_settings()     把设置 / 名单 / 悬浮窗配置导出成一个 zip
    import_settings()     从 zip 导回来（先自动备份现在那份）
"""
import json
import os
import platform
import shutil
import sys
import time
import zipfile
from pathlib import Path

import paths

APP_NAME = "StatGI"
# 导出 / 导入包里带的文件（相对项目根目录）
EXPORT_FILES = (
    ("config/settings.json", "设置"),
    ("data/names.json", "识别名单"),
    ("data/bar_items.json", "悬浮窗配置"),
    ("data/bar_presets.json", "悬浮窗预设"),
    ("data/favorites.json", "收藏夹"),
)


def _stamp():
    return time.strftime("%Y%m%d_%H%M%S")


def _tail_lines(p, n=400):
    """读一个文件最后 n 行（文件很大时别整个读进来）"""
    try:
        if not p.exists():
            return []
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            buf = f.readlines()
        return buf[-n:]
    except Exception:
        return []


# ---------------------------------------------------------------- 识别日志

def log_stats():
    """识别日志的现状（给设置页显示一行小字用）

    返回 dict：
        files     文件夹里几个日志文件
        bytes     一共多少字节
        current   本次正在写的那个文件名（没有就 "")
        lines     本次那个文件多少行
        dir       文件夹路径（字符串）
    """
    import detect_log
    d = detect_log.LOG_DIR
    files, total = 0, 0
    try:
        for p in d.glob("*.log"):
            if p.is_file():
                files += 1
                total += p.stat().st_size
    except Exception:
        pass
    cur = detect_log.current_file()
    lines = 0
    if cur is not None and cur.exists():
        try:
            with open(cur, "r", encoding="utf-8", errors="replace") as f:
                lines = sum(1 for _ in f)
        except Exception:
            lines = 0
    return {"files": files, "bytes": total,
            "current": (cur.name if cur is not None else ""),
            "lines": lines, "dir": str(d)}


def human_size(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def clear_logs(keep_current=False):
    """清空识别日志，返回 (删了几个, 省了多少字节)。

    keep_current=True 时留着"本次正在写的"那个文件。
    ⚠ 正在识别也没关系：日志文件是每次写的时候才打开的，删掉不会出错，
      下一次写入会自动重建。
    """
    import detect_log
    cur = detect_log.current_file()
    removed, freed = 0, 0
    try:
        for p in sorted(detect_log.LOG_DIR.glob("*.log")):
            if keep_current and cur is not None and p == cur:
                continue
            try:
                n = p.stat().st_size
                p.unlink()
                removed += 1
                freed += n
            except Exception:
                pass
    except Exception:
        pass
    return removed, freed


# ---------------------------------------------------------------- 诊断打包

def diagnose_text():
    """一份"环境概况"，出问题时先看这个"""
    lines = []
    try:
        from qt_pages import VERSION
    except Exception:
        VERSION = "未知"
    lines.append(f"{APP_NAME} {VERSION}")
    lines.append(f"打包时间：{time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("---- 运行环境 ----")
    lines.append(f"Python：{sys.version.split()[0]}（{platform.architecture()[0]}）")
    lines.append(f"系统：{platform.platform()}")
    lines.append(f"程序目录：{paths.app_dir()}")
    lines.append(f"打包运行：{'是' if getattr(sys, 'frozen', False) else '否（源码运行）'}")
    try:
        from PySide6 import QtCore
        lines.append(f"Qt：{QtCore.qVersion()}")
    except Exception:
        pass
    try:
        from PySide6.QtGui import QGuiApplication
        scr = QGuiApplication.primaryScreen()
        if scr is not None:
            g = scr.geometry()
            lines.append(f"屏幕：{g.width()}×{g.height()}　"
                         f"缩放 {round(scr.devicePixelRatio(), 2)}　"
                         f"逻辑 DPI {round(scr.logicalDotsPerInch(), 1)}")
    except Exception:
        pass
    try:
        import config_manager
        s = config_manager.load_settings()
        lines.append("")
        lines.append("---- 关键设置 ----")
        for k in ("tick_interval", "ocr_interval", "change_threshold",
                  "event_end_window", "only_foreground", "close_behavior",
                  "enable_mora", "enable_material", "enable_artifact",
                  "mora_max_amount", "ui_scale", "rollover_enabled",
                  "rollover_hour", "log_detections", "obs_api_enabled",
                  "api_port", "update_channel"):
            if k in s:
                lines.append(f"    {k} = {s.get(k)}")
    except Exception:
        pass
    lines.append("")
    lines.append("---- 数据文件 ----")
    data = paths.app_dir() / "data"
    try:
        for p in sorted(data.glob("*.json")):
            try:
                lines.append(f"    {p.name}　{p.stat().st_size} 字节")
            except Exception:
                pass
    except Exception:
        pass
    try:
        import svc_records
        lines.append(f"    收益记录 {len(svc_records.load_sessions())} 条　"
                     f"收藏夹 {len(svc_records.load_favorites())} 条")
    except Exception:
        pass
    return "\n".join(lines)


def collect_diagnose(dest_dir=None):
    """把诊断信息打包成一个 zip，返回那个 zip 的路径（失败返回 None）。

    装进去的东西：
        环境概况.txt      版本 / 系统 / 屏幕 / 关键设置 / 数据文件
        设置.json         完整设置（方便复现）
        报错日志.txt      data/error.log 的最后 400 行
        识别日志_最近.txt  最近那个识别日志的最后 400 行
        traceback.txt     如果有 Qt/Python 的崩溃记录也带上
    """
    try:
        import detect_log
        if dest_dir is None:
            # 优先放桌面 —— 用户下一步就是要把它发出去
            desk = Path(os.path.expanduser("~")) / "Desktop"
            dest_dir = desk if desk.is_dir() else paths.app_dir()
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        out = dest_dir / f"{APP_NAME}诊断_{_stamp()}.zip"

        app = paths.app_dir()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("环境概况.txt", diagnose_text())
            sp = app / "config" / "settings.json"
            if sp.exists():
                try:
                    z.write(sp, "设置.json")
                except Exception:
                    pass
            tail = _tail_lines(app / "data" / "error.log", 400)
            if tail:
                z.writestr("报错日志.txt", "".join(tail))
            cur = detect_log.current_file()
            if cur is not None:
                tl = _tail_lines(cur, 400)
                if tl:
                    z.writestr("识别日志_最近.txt", "".join(tl))
        return out
    except Exception:
        return None


# ---------------------------------------------------------------- 设置导出 / 导入

def export_settings(dest_zip):
    """把设置 / 名单 / 悬浮窗配置打包，返回 zip 路径（失败 None）"""
    try:
        app = paths.app_dir()
        dest_zip = Path(dest_zip)
        if dest_zip.suffix.lower() != ".zip":
            dest_zip = dest_zip.with_suffix(".zip")
        dest_zip.parent.mkdir(parents=True, exist_ok=True)
        try:
            from qt_pages import VERSION
        except Exception:
            VERSION = "?"
        names = []
        with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as z:
            for rel, label in EXPORT_FILES:
                p = app / rel
                if p.exists():
                    z.write(p, rel)
                    names.append(label)
            z.writestr("备份说明.txt",
                       f"{APP_NAME} 设置备份\n"
                       f"版本：{VERSION}\n"
                       f"时间：{time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                       f"包含：{'、'.join(names) if names else '（空的）'}\n\n"
                       "用法：在「设置 → 开发 → 设置备份」里点「导入」，选这个文件。\n")
        return dest_zip
    except Exception:
        return None


def import_settings(src_zip):
    """从 zip 导入，返回 (导入了哪些文件, 备份目录)。

    ⚠ 动手之前先把现在这份**原样备份**到 data/导入前备份_<时间>/，
      导错了还能自己拷回来。
    """
    app = paths.app_dir()
    src_zip = Path(src_zip)
    backup = app / "data" / f"导入前备份_{_stamp()}"
    done = []
    with zipfile.ZipFile(src_zip, "r") as z:
        members = set(z.namelist())
        targets = [(rel, label) for rel, label in EXPORT_FILES if rel in members]
        if not targets:
            raise ValueError("这个文件里没有可导入的内容（不是 StatGI 的设置备份？）")
        need = [(rel, label) for rel, label in targets if (app / rel).exists()]
        if need:                      # 先备份
            backup.mkdir(parents=True, exist_ok=True)
            for rel, _label in need:
                try:
                    shutil.copy2(app / rel, backup / Path(rel).name)
                except Exception:
                    pass
        for rel, label in targets:
            p = app / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            with z.open(rel) as fsrc, open(p, "wb") as fdst:
                shutil.copyfileobj(fsrc, fdst)
            done.append(label)
    return done, backup
