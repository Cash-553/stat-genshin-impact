# -*- coding: utf-8 -*-
"""直播间挂机 —— 这个模块真正干活的代码。

删掉 `modules/hang/` 就没有"打开直播间挂机"这个能力了。
（原来是和 OBS 挤在同一个函数里的，2026-10-13 拆开。）
"""
import os

from modules import common

CHROME_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
)


def detect_chrome():
    """找 chrome.exe（找不到返回 ""，那就交给系统默认浏览器）"""
    p = common.first_existing(CHROME_CANDIDATES)
    if p:
        return p
    p = common.scan_dir_for(os.environ.get("ProgramFiles", r"C:\Program Files"),
                            "Chrome", os.path.join("Application", "chrome.exe"))
    if p:
        return p
    return common.scan_dir_for(
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        "Chrome", os.path.join("Application", "chrome.exe"))


def available(c):
    """装了 + 开关开着 + 填了直播间地址"""
    try:
        mods = (c or {}).get("modules") or {}
        if not mods.get("hang", True):
            return False
        if not (c or {}).get("hang_enabled", True):
            return False
        return bool(str((c or {}).get("live_url") or "").strip())
    except Exception:
        return False


def steps(c):
    """到点要执行的动作：用浏览器打开直播间"""
    if not available(c):
        return []
    url = str((c or {}).get("live_url") or "").strip()
    chrome = str((c or {}).get("chrome_exe") or "").strip() or detect_chrome()
    return [{"label": "打开直播间", "exe": chrome,
             "args": ["--new-window", url] if chrome else [],
             "url": url, "steam_url": "", "delay": 0}]


# ---- 从 svc_autostart 搬过来的常量（原来留在主文件里，模块引用不到就报 NameError）----
CHROME_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
)

