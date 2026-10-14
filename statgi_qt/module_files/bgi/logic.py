# -*- coding: utf-8 -*-
"""BetterGI 模块 —— 探测/查询相关逻辑（2026-10-13 从 svc_autostart 搬来）。

这里只放"跟 BetterGI 打交道"的事：找它在哪、读它的调度器组名、找它的日志、
结束旧实例。**任务计划 / bat 生成 / 立即运行** 是通用调度核心，留在
`svc_autostart.py`（它不认识 BetterGI 这三个字）。

删掉 `modules/bgi/` 整个文件夹 → 这些能力就没了（只剩通用调度）。
"""
import json
import os
import subprocess
from pathlib import Path


def bgi_running(name="BetterGI.exe"):
    code, out = _run(["tasklist", "/FI", f"IMAGENAME eq {name}", "/NH"])
    return str(name).lower() in (out or "").lower()

def kill_bgi(name="BetterGI.exe"):
    """结束旧的 BGI 进程；返回是否真的杀掉了什么"""
    if not bgi_running(name):
        return False
    _run(["taskkill", "/IM", name, "/F"])
    return True

def _bgi_bases(bgi_dir="", exe=""):
    """BGI 可能的安装根目录（按可信度排序）"""
    out = []
    for cand in (bgi_dir, str(Path(exe).parent) if exe else ""):
        if cand:
            p = Path(str(cand))
            if p not in out:
                out.append(p)
    try:
        found = detect_bgi()
        for cand in (found or ()):
            p = Path(str(cand))
            if p not in out:
                out.append(p)
    except Exception:
        pass
    return out

def bgi_groups(bgi_dir="", exe=""):
    """读 BetterGI 调度器的分组名（`User/ScriptGroup/*.json` 里的 name）。

    用户 2026-10-13：配置组改成下拉，直接从 BGI 里读，免得手抄错名字。
    BGI 里新建的组要重启本程序（或点下拉底部的「刷新组名列表」）才会出现。
    找不到就返回空列表（界面会退化成可以手输）。
    """
    for base in _bgi_bases(bgi_dir, exe):
        d = Path(base) / "User" / "ScriptGroup"
        if not d.is_dir():
            continue
        items = []
        for f in sorted(d.glob("*.json")):
            nm, idx = f.stem, 0
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                nm = str(data.get("name") or f.stem).strip() or f.stem
                idx = int(data.get("index") or 0)
            except Exception:
                pass
            items.append((idx, nm))
        if items:
            return [nm for _i, nm in sorted(items, key=lambda x: (x[0], x[1]))]
    return []

def bgi_log_dir(bgi_dir="", exe=""):
    for base in _bgi_bases(bgi_dir, exe):
        d = Path(base) / "log"
        if d.is_dir():
            return d
    return None

def latest_bgi_log(bgi_dir="", exe=""):
    """最新的 BGI 日志文件；找不到返回 None"""
    d = bgi_log_dir(bgi_dir, exe)
    if d is None:
        return None
    try:
        files = [p for p in d.glob("*.log") if p.is_file()]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return files[0] if files else None
    except Exception:
        return None

def tail_text(path, lines=200, max_bytes=400000):
    """读文件尾部若干行（日志可能很大，只读尾巴）"""
    try:
        p = Path(path)
        size = p.stat().st_size
        with open(p, "rb") as f:
            if size > max_bytes:
                f.seek(-max_bytes, 2)
                f.readline()          # 丢掉半行
            raw = f.read()
        text = raw.decode("utf-8", "replace")
        return "\n".join(text.splitlines()[-lines:])
    except Exception as e:
        return f"（读不了日志：{e}）"

def detect_bgi():
    """猜 BetterGI 装在哪：先看常见目录，再问注册表/快捷方式附近。

    返回 (bgi_dir, bgi_exe)——找不到就是两个空串。
    """
    cands = []
    for d in BGI_HINTS:
        cands.append(Path(d))
    # 桌面快捷方式指向的位置（有就顺手解析一下）
    try:
        desk = Path(os.environ.get("USERPROFILE", "")) / "Desktop"
        for lnk in desk.glob("*.lnk"):
            if "better" in lnk.name.lower() or "bgi" in lnk.name.lower():
                try:
                    import ctypes.wintypes as wt
                    # 简化的 lnk 解析：只用 PowerShell 读 TargetPath
                    code, out = _run([
                        "powershell", "-NoProfile", "-Command",
                        f"(New-Object -ComObject WScript.Shell)."
                        f"CreateShortcut('{lnk}').TargetPath"], timeout=20)
                    if code == 0 and out.strip():
                        cands.insert(0, Path(out.strip()).parent)
                except Exception:
                    pass
    except Exception:
        pass
    for d in cands:
        exe = d / "BetterGI.exe"
        try:
            if exe.is_file():
                return str(d), str(exe)
        except Exception:
            continue
    return "", ""


def steps(config):
    """BGI 启动模块提供给公共调度器的标准动作。"""
    c = config or {}
    from modules import load_config
    c = dict(c)
    c.update(load_config("bgi", c))
    if not c.get("bgi_exe"):
        directory, exe_path = detect_bgi()
        if exe_path:
            c["bgi_dir"], c["bgi_exe"] = directory, exe_path
    exe = str(c.get("bgi_exe") or "").strip()
    if not exe:
        return []
    groups = [str(g).strip() for g in c.get("groups", []) if str(g).strip()]
    args = ["--startGroups", *groups] if groups else []
    return [{
        "label": "启动 BetterGI",
        "exe": exe,
        "args": args,
        "url": "",
        "steam_url": "",
        "cwd": str(c.get("bgi_dir") or Path(exe).parent),
        "kill_process": "BetterGI.exe" if c.get("kill_existing_bgi", True) else "",
        "pre_delay": 5 if c.get("kill_existing_bgi", True) else 0,
    }]


def collect_ui(tab, config):
    """收集 BGI 自己的界面字段，公共页面无需识别这些字段。"""
    from modules import load_config
    c = load_config("bgi", config)
    c["bgi_dir"] = (tab.dir_entry.text() or "").strip()
    c["bgi_exe"] = (tab.exe_entry.text() or "").strip()
    c["kill_existing_bgi"] = bool(tab.switch_kill.isChecked())
    c["groups"] = [name for name, box in getattr(tab, "_group_boxes", [])
                    if box.isChecked()]
    c["auto_monitor_group"] = tab.mon_list.value() if getattr(tab, "mon_list", None) else ""
    c["stop_after_group"] = tab.stop_list.value() if getattr(tab, "stop_list", None) else ""
    return c


def monitor_settings(config):
    """模块向监测核心提供自动开始/停止与目标进程设置。"""
    from modules import load_config
    return load_config("bgi", config)


# ---- 从 svc_autostart 搬过来的常量（原来留在主文件里，模块引用不到就报 NameError）----
BGI_HINTS = [r"D:\BetterGI", r"C:\BetterGI", r"D:\Program Files\BetterGI",
             r"C:\Program Files\BetterGI"]


def defaults():
    return {"bgi_dir": "", "bgi_exe": "", "groups": [],
            "kill_existing_bgi": True, "auto_monitor_group": "",
            "stop_after_group": ""}

