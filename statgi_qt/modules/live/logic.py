# -*- coding: utf-8 -*-
"""直播插件（OBS）—— 这个模块真正干活的代码。

只要这个文件夹在，模块就在；删掉整个 `modules/live/`，本程序就**不再有**
OBS 直播能力（不是藏起来，是代码都不在）。
"""
import os
import re
from pathlib import Path

from modules import common

OBS_CANDIDATES = (
    r"C:\Program Files\obs-studio\bin\64bit\obs64.exe",
    r"C:\Program Files (x86)\obs-studio\bin\64bit\obs64.exe",
    r"D:\Program Files\obs-studio\bin\64bit\obs64.exe",
    r"E:\Program Files\obs-studio\bin\64bit\obs64.exe",
)


def _obs_from_registry():
    """从注册表卸载信息里找 OBS（Steam 版也在这里能找到）"""
    try:
        import winreg
    except Exception:
        return ""
    roots = (
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    )
    for hive, root in roots:
        try:
            with winreg.OpenKey(hive, root) as k:
                n = winreg.QueryInfoKey(k)[0]
                for i in range(n):
                    try:
                        sub = winreg.EnumKey(k, i)
                        with winreg.OpenKey(k, sub) as sk:
                            try:
                                name = str(winreg.QueryValueEx(sk, "DisplayName")[0])
                            except Exception:
                                continue
                            if "obs" not in name.lower():
                                continue
                            try:
                                loc = str(winreg.QueryValueEx(sk, "InstallLocation")[0])
                            except Exception:
                                continue
                            for rel in (os.path.join("bin", "64bit", "obs64.exe"),
                                        "obs64.exe"):
                                p = os.path.join(loc, rel)
                                if os.path.isfile(p):
                                    return p
                    except Exception:
                        continue
        except Exception:
            continue
    return ""


def detect_obs():
    """找 obs64.exe（找不到返回 ""，不抛异常）"""
    p = common.first_existing(OBS_CANDIDATES)
    if p:
        return p
    p = _obs_from_registry()
    if p:
        return p
    for root in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                 os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                 "D:\\", "E:\\", "D:\\Program Files", "E:\\Program Files",
                 r"C:\Program Files (x86)\Steam\steamapps\common",
                 r"D:\Steam\steamapps\common",
                 r"E:\Steam\steamapps\common"):
        for pat in ("obs-studio", "OBS Studio"):
            p = common.scan_dir_for(root, pat,
                                    os.path.join("bin", "64bit", "obs64.exe"))
            if p:
                return p
    return ""


def steam_appid_for(exe_path):
    """从 OBS 路径反推 Steam AppID（Steam 版才有）"""
    try:
        p = Path(str(exe_path or "")).resolve()
    except Exception:
        return ""
    for parent in p.parents:
        if parent.name.lower() != "steamapps":
            continue
        try:
            for acf in parent.glob("appmanifest_*.acf"):
                try:
                    txt = acf.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
                m = re.search(r'"name"\s*"([^"]+)"', txt)
                if not m or "obs" not in m.group(1).lower():
                    continue
                m2 = re.search(r'"appid"\s*"(\d+)"', txt)
                if m2:
                    return m2.group(1)
                m3 = re.search(r"appmanifest_(\d+)\.acf", acf.name)
                if m3:
                    return m3.group(1)
        except Exception:
            pass
        return ""
    return ""


def available(c):
    """这个模块这次要不要执行（装了 + 开关开着）"""
    try:
        mods = (c or {}).get("modules") or {}
        return bool(mods.get("live", True)) and bool((c or {}).get("live_enabled"))
    except Exception:
        return False


def steps(c):
    """到点要执行的动作（返回统一形状的 dict 列表）"""
    if not available(c):
        return []
    obs = str((c or {}).get("obs_exe") or "").strip() or detect_obs()
    if not obs:
        return []
    args = []
    if (c or {}).get("obs_start_stream", True):
        args.append("--startstreaming")
    if (c or {}).get("obs_minimize", True):
        args.append("--minimize-to-tray")
    via_steam = bool((c or {}).get("obs_via_steam"))
    appid = steam_appid_for(obs) if via_steam else ""
    if via_steam and appid:
        # 走 Steam 启动：好友列表会显示；但 steam:// 传不了参数，
        # 自动开播要在 Steam 的「启动选项」里自己加
        return [{"label": "OBS 开播（Steam）", "exe": "", "args": [], "url": "",
                 "steam_url": f"steam://rungameid/{appid}", "delay": 0}]
    return [{"label": "OBS 开播", "exe": obs, "args": args, "url": "",
             "steam_url": "", "delay": 0}]


# ---- 从 svc_autostart 搬过来的常量（原来留在主文件里，模块引用不到就报 NameError）----
OBS_CANDIDATES = (
    r"C:\Program Files\obs-studio\bin\64bit\obs64.exe",
    r"C:\Program Files (x86)\obs-studio\bin\64bit\obs64.exe",
    r"D:\Program Files\obs-studio\bin\64bit\obs64.exe",
    r"E:\Program Files\obs-studio\bin\64bit\obs64.exe",
)

