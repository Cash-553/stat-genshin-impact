# -*- coding: utf-8 -*-
"""自动运行服务 —— 定时拉起外部程序（如 BetterGI）+ 配合自动开始/停止监测。

移植自用户自己的 `E:\\开门助手`（config.py / scheduler.py / launcher.py），
按本项目的分层要求收进一个服务模块（UI 只跟这里打交道）。

做四件事：

    1. **Windows 任务计划**：按"每天几点 + 星期几"建/删任务（schtasks + XML），
       任务以最高权限运行（XML 里 RunLevel=HighestAvailable）→ 运行时不再弹 UAC
    2. **生成启动脚本**：exe 旁边的 `自动运行.bat`（UTF-8-BOM + chcp 65001）
    3. **拉起 / 结束目标程序**：默认是 BetterGI 的 `--startGroups 开门 狗粮 锄地`
    4. **状态计算**：下次运行时间、今天要不要跳过（排除日期）

⚠ 两个跟原工具的**实质差别**（原工具在这两处有问题，移植时修掉）：

    · **排除日期原来是没生效的**：原做法是给每个排除日 D 额外加一条
      「D 前一天」的一次性触发器，注释说"用于状态提示" —— 但那条触发器
      到点**会真的执行 bat**，而 D 当天那条**每周触发器照样会跑**。
      所以"这些日子永远不跑"并没有实现。
      → 本实现：触发器只留每周那一条，**排除日期交给 bat 自己判断**（当天跳过），
        界面上的"下次运行"由 Python 计算时直接跳过这些日子。
    · **管理员权限只在"建/删任务"那一刻要**：原工具要求整个程序以管理员重启；
      这里改成用 `ShellExecuteW runas` **只提权那一次**（弹一次 UAC），
      程序本身照常跑。

⚠ 主程序**只是拉起用户指定的第三方程序**，自己不注入、不读游戏内存、不模拟操作。
"""
import ctypes
import json
import os
import re
import subprocess
import sys
import tempfile
import xml.sax.saxutils as sx
from datetime import date, datetime, timedelta
from pathlib import Path

import paths

def _load_module_logic(name):
    """加载某个模块的 logic.py（开发环境 / 打包后 / 用户目录 都能找到）。

    2026-10-13 踩过两次坑：
      · 开发环境有 .py 文件，按路径能加载 ✓
      · 打包后模块被编译进程序内部，磁盘上没有 .py ✗ → 按路径找不到 ✗
      · 程序旁边那个给用户看的 `modules` 文件夹跟包同名，会顶掉正常导入 ✗
    所以**逐条都试**：
      ① 跟本文件同级（开发环境）
      ② PyInstaller 解包目录 _MEIPASS / exe 旁边的 _internal（打包后）
      ③ 用户看得见的 modules 文件夹
      ④ 最后退回正常 import
    """
    import importlib.util
    import sys as _sys
    from pathlib import Path as _P

    cands = []
    try:
        cands.append(_P(__file__).resolve().parent / "modules" / name / "logic.py")
    except Exception:
        pass
    try:
        base = getattr(_sys, "_MEIPASS", None)
        if base:
            cands.append(_P(base) / "modules" / name / "logic.py")
            cands.append(_P(base) / "_internal" / "modules" / name / "logic.py")
    except Exception:
        pass
    try:
        exe_dir = _P(_sys.executable).resolve().parent
        cands.append(exe_dir / "_internal" / "modules" / name / "logic.py")
        cands.append(exe_dir / "modules" / name / "logic.py")
    except Exception:
        pass
    try:
        import paths
        cands.append(_P(paths.app_dir()) / "modules" / name / "logic.py")
    except Exception:
        pass

    for f in cands:
        try:
            if f.is_file():
                spec = importlib.util.spec_from_file_location(
                    "statgi_logic_" + name, f)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                return mod
        except Exception:
            continue
    for modname in ("statgi_qt.modules." + name + ".logic",
                    "modules." + name + ".logic"):
        try:
            import importlib
            return importlib.import_module(modname)
        except Exception:
            continue
    return None
# ---------------------------------------------------------------- 常量
WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
WEEKDAY_XML = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
               "Saturday", "Sunday"]
BAT_NAME = "自动运行.bat"
DEFAULT_TASK = "StatGI 自动运行"
# 常见安装位置（探测用）
BGI_HINTS = [r"D:\BetterGI", r"C:\BetterGI", r"D:\Program Files\BetterGI",
             r"C:\Program Files\BetterGI"]

# 设置里存的默认值（并进主设置文件 config/settings.json 的 "autostart" 键）
DEFAULT = {
    "enabled": False,          # 总开关：勾上并保存才建任务
    "time": "03:58",           # 每天几点
    "weekdays": [True] * 7,    # 周一..周日
    "exclude_dates": [],       # ["2026-10-01", ...] 这些日子不跑
    # ---- 模块（2026-10-12 用户要求：分模块，能开关/能卸载）----
    #   bgi  ：目标程序 + 配置组 + 自动监测，关掉这些选项就不显示也不执行
    #   live ：直播（OBS 开播 / 直播间挂机），可以**卸载**（卸载会清掉相关配置）
    "modules": {"bgi": True},   # 只有 bgi 是内置常驻；别的模块靠文件夹
    "groups": ["开门", "狗粮", "锄地"],   # 传给 BGI --startGroups 的配置组
    "bgi_dir": "",
    "bgi_exe": "",
    "task_name": DEFAULT_TASK,
    "kill_existing_bgi": True,  # 先杀旧 BGI，避免双实例抢窗口
    "wake_to_run": False,       # 睡眠也唤醒跑
    "auto_monitor": True,       # ★ 本项目的加分项：到点自动开始监测
    "auto_stop": True,          # 旧：目标程序退出后自动停止监测（已被下面两个取代）
    "start_self": True,          # ★ 到点也自动启动 StatGI 自己（不开=没人记账）
    "auto_monitor_group": "",    # ★ 启动这个配置组时自动开始监测（空=不自动开始）
    "stop_after_group": "",      # ★ 这个配置组结束后停止监测（空=不自动停止）
    # ---- 直播（2026-10-12 用户需求：到点顺便开播 + 挂直播间）----
    # 推流地址/场景/画质全在 OBS 自己里配好，这里只管"启动它并开播"
    "live_enabled": False,      # 到点是否执行下面这些直播动作
    "obs_exe": "",              # obs64.exe；留空 = 自动探测
    "obs_via_steam": False,     # 通过 Steam 启动（Steam 里才显示"正在运行"）
    "obs_start_stream": True,   # 启动 OBS 时自动开始推流（--startstreaming）
    "obs_minimize": True,       # 最小化到托盘（不挡游戏）
    "live_url": "",             # 直播间地址，用浏览器打开挂机
    "chrome_exe": "",           # 指定浏览器；留空 = 探测 Chrome，再不行用默认
    "live_delay": 0,            # 延迟 N 秒再开播（等游戏先进去）
    # 直播间挂机是**独立模块**（2026-10-12 用户要求从直播插件里切出来）
    "hang_enabled": True,       # 该模块的开关；装上了默认就启用
    # 外部导入的模块：{模块key: 是否启用}（key 形如 ext:名字）
    "external_on": {},
}


# ---------------------------------------------------------------- 模块目录
# 2026-10-12 用户要求：定时启动按模块组织，而且以后能**随意添加模块**。
# 想加新模块：往下面这个元组里加一条，再在 `qt_settings_tabs.AutostartTab`
# 里给它做一张卡片 + 一个折叠区即可（界面上的「添加模块」会自动列出来）。
def _load_modules():
    """从 `statgi_qt/modules/<名字>/module.py` 加载模块清单。

    2026-10-13 用户要求：一个模块一个文件夹，**删文件夹 = 删模块**。
    之前这里是个写死的元组，删模块必须改代码 ✗。
    加载器读不到就返回一个小兜底（只保证程序不炸，不假装模块还在）。
    """
    try:
        import modules as _m
        got = _m.load_all()
        if got:
            return tuple(got)
    except Exception:
        pass
    return ({"key": "bgi", "name": "BetterGI 模块", "builtin": True,
             "desc": "目标程序、连续执行配置组、到点自动开始/停止监测",
             "order": 10, "folder": "bgi", "path": ""},)


MODULES = _load_modules()


def module_info(key):
    for m in MODULES:
        if m["key"] == key:
            return m
    return {"key": key, "name": key, "builtin": False, "desc": ""}


# ---------------------------------------------------------------- 配置
def cfg(settings):
    """从主设置里取自动运行配置（缺键补默认值，坏值回退）"""
    raw = {}
    try:
        raw = dict((settings or {}).get("autostart") or {})
    except Exception:
        raw = {}
    out = dict(DEFAULT)
    out.update({k: v for k, v in raw.items() if k in DEFAULT})
    if not isinstance(out.get("weekdays"), list) or len(out["weekdays"]) != 7:
        out["weekdays"] = list(DEFAULT["weekdays"])
    for k in ("groups", "exclude_dates"):
        if not isinstance(out.get(k), list):
            out[k] = list(DEFAULT[k])
    if parse_time(out.get("time")) is None:
        out["time"] = DEFAULT["time"]
    # 模块：坏值/缺键都回落到默认（默认两个都开）
    mods = out.get("modules")
    if not isinstance(mods, dict):
        mods = {}
    ext = out.get("external_on")
    out["external_on"] = {str(k): bool(v) for k, v in ext.items()} \
        if isinstance(ext, dict) else {}
    out["modules"] = {"bgi": bool(mods.get("bgi", True)),
                      "live": bool(mods.get("live", True)),
                      "hang": bool(mods.get("hang", True))}
    good, _bad = parse_exclude_dates(out.get("exclude_dates"))
    out["exclude_dates"] = good
    return out


def module_installed(name):
    """这个模块到底在不在（**看文件夹**，不看配置）。

    2026-10-13：配置里的 modules 只保留了 bgi，别的模块是否"装"取决于
    `statgi_qt/modules/<name>/` 或程序旁边那个 modules 文件夹里有没有它。
    """
    try:
        import modules as _m
        return any(m["key"] == name for m in _m.load_all())
    except Exception:
        return False


def mod_on(c, name):
    """模块是否启用（bgi / live）。缺键当"开" —— 老配置直接升级不留坑。"""
    try:
        return bool((c.get("modules") or {}).get(name, True))
    except Exception:
        return True


def save_into(settings, values):
    """把改动写回主设置字典（调用方负责落盘）"""
    cur = cfg(settings)
    cur.update(values or {})
    settings["autostart"] = cur
    return cur


def parse_time(text):
    """'03:58' -> (3, 58)；非法返回 None"""
    try:
        parts = str(text).strip().split(":")
        if len(parts) != 2:
            return None
        h, m = int(parts[0]), int(parts[1])
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h, m
    except Exception:
        pass
    return None


def parse_exclude_dates(lines):
    """规范化排除日期：接受 2026-10-01 / 2026/10/01 / 20261001。

    返回 (合法列表, 非法列表)
    """
    good, bad = [], []
    for raw in (lines or []):
        s = str(raw).strip().replace("/", "-").replace(".", "-")
        if not s:
            continue
        digits = s.replace("-", "")
        if len(digits) == 8 and digits.isdigit():
            s = f"{digits[0:4]}-{digits[4:6]}-{digits[6:8]}"
        parts = s.split("-")
        ok = (len(parts) == 3 and all(p.isdigit() for p in parts)
              and len(parts[0]) == 4 and 1 <= int(parts[1]) <= 12
              and 1 <= int(parts[2]) <= 31)
        if ok:
            if s not in good:
                good.append(s)
        else:
            bad.append(str(raw).strip())
    return sorted(good), bad


def active_weekdays(c):
    return [i for i, on in enumerate(c.get("weekdays", [])) if on]


def skipped_today(c, today=None):
    """今天是不是被"排除日期"跳过的"""
    d = (today or date.today()).isoformat()
    return d in (c.get("exclude_dates") or [])


def runs_today(c, today=None):
    """今天按配置该不该跑（星期几 + 排除日期）"""
    t = today or date.today()
    if not c.get("enabled", False):
        return False
    if t.weekday() not in active_weekdays(c):
        return False
    return not skipped_today(c, t)


def next_run(c, now=None):
    """算下一次运行时刻（跳过排除日期）；返回 datetime 或 None"""
    hhmm = parse_time(c.get("time"))
    if not hhmm or not active_weekdays(c):
        return None
    now = now or datetime.now()
    hh, mm = hhmm
    for i in range(0, 400):                     # 往后找 400 天足够
        d = (now + timedelta(days=i)).date()
        if d.weekday() not in active_weekdays(c):
            continue
        if d.isoformat() in (c.get("exclude_dates") or []):
            continue
        cand = datetime(d.year, d.month, d.day, hh, mm)
        if cand > now:
            return cand
    return None


# ---------------------------------------------------------------- 权限
def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def get_user_id():
    import getpass
    domain = os.environ.get("USERDOMAIN") or ""
    user = os.environ.get("USERNAME") or getpass.getuser()
    return f"{domain}\\{user}" if domain else user


def _run(args, timeout=30):
    """跑一个命令（不弹窗），返回 (返回码, 输出)"""
    try:
        r = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()
    except FileNotFoundError:
        return 1, "找不到命令（schtasks.exe？）"
    except Exception as e:
        return 1, f"{type(e).__name__}: {e}"


def run_elevated(exe, args):
    """以管理员身份跑一条命令（**只提权这一次**，弹一次 UAC）。

    用 PowerShell 的 `Start-Process -Verb RunAs -Wait`：它自带 UAC 提示，
    跑完返回。提权后父进程**拿不到子进程输出**，所以调用方靠
    "事后查一遍结果"（比如 task_exists）来判断成没成。
    """
    try:
        quoted = ", ".join("'" + str(a).replace("'", "''") + "'" for a in args)
        script = (f"Start-Process -FilePath '{exe}' "
                  f"-ArgumentList {quoted} -Verb RunAs -Wait")
        r = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-Command", script],
            capture_output=True, text=True, timeout=180,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        if r.returncode == 0:
            return True, out or "已提权执行"
        # 用户点了"否" → PowerShell 报这个
        if "canceled" in out.lower() or "已取消" in out or "拒绝" in out:
            return False, "用户取消了 UAC 提权"
        return False, out or f"提权执行失败（代码 {r.returncode}）"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------- 直播（OBS）
# 用户 2026-10-12：到点顺便开直播 —— OBS 推流（推流/场景他自己在 OBS 里配好了），
# 再开 Chrome 打开直播间挂机。
#
# 实现方式：**不给 OBS 传场景/推流地址**（那些在 OBS 自己的配置里），只：
#   ① 用 `--startstreaming` 让它启动即开播
#   ② 用 `--minimize-to-tray` 让它别挡着游戏
# 这样 OBS 里怎么配的，就按怎么播；本程序不碰任何推流码/密钥。
OBS_CANDIDATES = (
    r"C:\Program Files\obs-studio\bin\64bit\obs64.exe",
    r"C:\Program Files (x86)\obs-studio\bin\64bit\obs64.exe",
    r"D:\Program Files\obs-studio\bin\64bit\obs64.exe",
    r"E:\Program Files\obs-studio\bin\64bit\obs64.exe",
)
CHROME_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
)


def _first_existing(paths):
    for p in paths:
        try:
            if p and os.path.isfile(p):
                return p
        except Exception:
            continue
    return ""


def _scan_dir_for(root, pattern, rel):
    """在 `root\\<*pattern*>` 下找 `rel`（OBS 可能装在别的盘/别的目录名）"""
    try:
        if not os.path.isdir(root):
            return ""
        for name in os.listdir(root):
            if pattern.lower() in name.lower():
                p = os.path.join(root, name, rel)
                if os.path.isfile(p):
                    return p
    except Exception:
        pass
    return ""








def live_steps(c):
    """把各模块的"到点要做什么"汇总起来（统一形状的 list）。

    2026-10-13：改成**问模块要** —— 每个模块文件夹自己提供 `logic.steps(c)`，
    主程序不认识 OBS/浏览器这些东西了。删掉某个模块文件夹，它的步骤自然消失。
    """
    if not c:
        return []
    steps = []
    for name in ("live", "hang"):
        m = _mod_logic(name)
        if m is None:
            continue
        try:
            steps += m.steps(c)
        except Exception:
            pass
    # 外部导入的模块（声明式，不执行第三方代码）
    try:
        import svc_modules
        steps += svc_modules.external_steps(c)
    except Exception:
        pass
    return steps


def build_live_bat_lines(c):
    """把 `live_steps` 变成 bat 里的几行（`start` 拉起，不等它退出）"""
    steps = live_steps(c)
    if not steps:
        return []
    lines = ["", "rem ---- 直播（OBS 开播 / 打开直播间）----"]
    try:
        delay = int(c.get("live_delay") or 0)
    except Exception:
        delay = 0
    if delay > 0:
        lines.append(f"rem 等 {delay} 秒再开播，让游戏先进去")
        lines.append(f"timeout /t {delay} /nobreak >nul")
    for s in steps:
        exe, args = s["exe"], s["args"]
        if s.get("steam_url"):
            # 走 Steam 启动（好友列表里会显示"正在玩 OBS"）
            lines.append(f'start "" "{s["steam_url"]}"')
        elif exe:
            # /D 指定工作目录：OBS 必须在自己目录里跑才认自己的配置
            d = os.path.dirname(exe)
            a = (" " + " ".join(f'"{x}"' if " " in x else x for x in args)) if args else ""
            try:
                sd = int(s.get("delay") or 0)
            except Exception:
                sd = 0
            if sd > 0:
                lines.append(f"timeout /t {sd} /nobreak >nul")
            lines.append(f'start "" /D "{d}" "{exe}"{a}')
        elif s["url"]:
            # 没找到指定浏览器 → 交给系统默认浏览器
            lines.append(f'start "" "{s["url"]}"')
    return lines


def start_live(c):
    """立刻执行直播动作（"立即运行一次"用）。返回中文说明列表。"""
    notes = []
    for s in live_steps(c):
        try:
            if s.get("steam_url"):
                os.startfile(s["steam_url"])       # noqa: S606 - Steam 协议链接
                notes.append(f"{s['label']}（已交给 Steam）")
            elif s["exe"]:
                flags = 0x00000008 | 0x00000200    # DETACHED_PROCESS | NEW_PROCESS_GROUP
                subprocess.Popen([s["exe"]] + list(s["args"]),
                                 cwd=os.path.dirname(s["exe"]) or None,
                                 close_fds=True, creationflags=flags)
                notes.append(f"{s['label']}（已启动）")
            elif s["url"]:
                os.startfile(s["url"])             # noqa: S606 - 用户自己填的网址
                notes.append(f"{s['label']}（用默认浏览器打开）")
        except Exception as e:
            notes.append(f"{s['label']}失败：{type(e).__name__}: {e}")
    return notes



# ---------------------------------------------------------------- BGI 模块别名
# 2026-10-13：BetterGI 的探测/查询代码搬进了 `statgi_qt/modules/bgi/logic.py`。
# 这里转发一下，老代码/测试继续用 `svc_autostart.detect_bgi()` 这些名字。
def _bgi_logic():
    return _load_module_logic("bgi")


_bgi = _bgi_logic()


def detect_bgi():
    return _bgi.detect_bgi() if _bgi else ("", "")


def bgi_running(name="BetterGI.exe"):
    return _bgi.bgi_running(name) if _bgi else False


def kill_bgi(name="BetterGI.exe"):
    return _bgi.kill_bgi(name) if _bgi else False


def bgi_groups(bgi_dir="", exe=""):
    return _bgi.bgi_groups(bgi_dir, exe) if _bgi else []


def latest_bgi_log(bgi_dir="", exe=""):
    return _bgi.latest_bgi_log(bgi_dir, exe) if _bgi else None


def tail_text(path, lines=200, max_bytes=400000):
    return _bgi.tail_text(path, lines, max_bytes) if _bgi else ""

# ---------------------------------------------------------------- 模块别名
# 2026-10-13：直播（OBS）和直播间挂机的代码已经搬进各自模块文件夹
# （`statgi_qt/modules/live/logic.py`、`modules/hang/logic.py`）。
# 这里只是**转发**，让老代码和测试继续用 `svc_autostart.detect_obs()` 这些名字。
# 删掉那两个文件夹，这里会安静地退化成"探测不到" —— 不会有残留的一半功能。
def _mod_logic(name):
    return _load_module_logic(name)


_live = _mod_logic("live")
_hang = _mod_logic("hang")



def detect_obs():
    return _live.detect_obs() if _live else ""


def steam_appid_for(exe_path):
    return _live.steam_appid_for(exe_path) if _live else ""


def detect_chrome():
    return _hang.detect_chrome() if _hang else ""

# ---------------------------------------------------------------- 任务计划
def _q(s):
    return sx.escape(str(s), {'"': "&quot;"})


def build_task_xml(c, bat_path, user_id):
    """生成任务计划 XML。

    ⚠ 触发器**只有每周那一条**。排除日期不在这里表达 —— Windows 的每周触发器
      没法表达"某个周三不跑"，硬塞额外触发器还会在别的日子把任务跑起来
      （原工具就是这么错的）。排除日期交给 bat 自己判断（见 `build_bat_text`）。
    """
    hhmm = parse_time(c.get("time"))
    if not hhmm:
        raise ValueError("时间格式不对（应形如 03:58）")
    if not active_weekdays(c):
        raise ValueError("没有勾选任何星期几，任务不会按周期触发。请至少勾选一天。")
    hh, mm = hhmm
    start = f"2000-01-03T{hh:02d}:{mm:02d}:00"
    days = [WEEKDAY_XML[i] for i in active_weekdays(c)]
    dow = "".join(f"<{d} />" for d in days)
    wake = "true" if c.get("wake_to_run") else "false"
    name = c.get("task_name") or DEFAULT_TASK
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>由 StatGI 生成：定时启动外部程序（如 BetterGI 的配置组）。</Description>
    <URI>\\{_q(name)}</URI>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{start}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByWeek>
        <DaysOfWeek>{dow}</DaysOfWeek>
        <WeeksInterval>1</WeeksInterval>
      </ScheduleByWeek>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{_q(user_id)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>{wake}</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{_q(bat_path)}</Command>
      <WorkingDirectory>{_q(c.get('bgi_dir') or '')}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def create_task(c, bat_path, elevate=True):
    """建/更新任务。没管理员权限时用 `run_elevated` 提权一次。

    返回 (成功?, 说明)
    """
    name = c.get("task_name") or DEFAULT_TASK
    try:
        xml = build_task_xml(c, bat_path, get_user_id())
    except Exception as e:
        return False, f"生成任务 XML 失败：{e}"

    tmp = Path(tempfile.gettempdir()) / "statgi_autostart_task.xml"
    try:
        with open(tmp, "w", encoding="utf-16") as f:   # schtasks 要 UTF-16
            f.write(xml)
    except Exception as e:
        return False, f"写临时 XML 失败：{e}"

    args = ["/Create", "/TN", name, "/XML", str(tmp), "/F"]
    if is_admin():
        code, out = _run(["schtasks"] + args)
    elif elevate:
        ok, out = run_elevated("schtasks.exe", args)
        code = 0 if ok else 1
    else:
        code, out = 1, "需要管理员权限才能创建任务计划"
    try:
        os.remove(tmp)
    except Exception:
        pass

    if code == 0 and task_exists(name):
        return True, f"任务「{name}」已创建/更新"
    return False, f"创建失败：{out}"


def delete_task(name, elevate=True):
    if task_exists(name) is False and not is_admin():
        return True, "任务不存在（无需删除）"
    args = ["/Delete", "/TN", name, "/F"]
    if is_admin():
        code, out = _run(["schtasks"] + args)
    elif elevate:
        ok, out = run_elevated("schtasks.exe", args)
        code = 0 if ok else 1
    else:
        code, out = 1, "需要管理员权限才能删除任务计划"
    if code == 0 or not task_exists(name):
        return True, f"任务「{name}」已删除"
    return False, f"删除失败：{out}"


def task_exists(name):
    if not name:
        return False
    code, _ = _run(["schtasks", "/Query", "/TN", name])
    return code == 0


def query_task(name):
    """返回 {exists, next_run, last_run, status}（解析不出来就是 None）"""
    info = {"exists": False, "next_run": None, "last_run": None, "status": None}
    if not name:
        return info
    code, out = _run(["schtasks", "/Query", "/TN", name, "/FO", "LIST", "/V"])
    if code != 0:
        return info
    info["exists"] = True
    for line in out.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k, v = k.strip().lower(), v.strip()
        if not v or v in ("N/A", "不适用"):
            continue
        if k in ("next run time", "下次运行时间"):
            info["next_run"] = v
        elif k in ("last run time", "上次运行时间"):
            info["last_run"] = v
        elif k in ("status", "状态"):
            info["status"] = v
    return info


def run_task_now(name):
    code, out = _run(["schtasks", "/Run", "/TN", name])
    if code == 0:
        return True, "已手动触发定时任务"
    return False, f"触发失败：{out}"


# ---------------------------------------------------------------- 启动脚本
def _self_launch_line():
    """"把自己拉起来"的命令：打包版直接跑 StatGI.exe，源码运行时跑 main.py"""
    import shutil
    import sys as _sys
    try:
        import paths
        app = paths.app_dir()
        exe = app / "StatGI.exe"
        if getattr(_sys, "frozen", False) and exe.is_file():
            return f'start "" /D "{app}" "{exe}"'
        # ⚠ 优先用"正在运行的这个解释器"（which pythonw 可能挑到
        #   WindowsApps 里那个坏掉的商店版存根 ✗）
        cands = []
        try:
            from pathlib import Path as _P
            _exe = _P(_sys.executable)
            cands.append(str(_exe.with_name("pythonw.exe")))
            cands.append(str(_exe))
        except Exception:
            pass
        cands += [shutil.which("pythonw"), shutil.which("python"), _sys.executable]
        py = next((c for c in cands if c and _P(c).is_file()), _sys.executable)
        main = app / "statgi_qt" / "main.py"
        if main.is_file():
            return f'start "" /D "{app}" "{py}" "{main}"'
    except Exception:
        pass
    return ""



def build_bat_text(c):
    """生成 bat 内容。

    要点（照搬原工具踩过的坑）：
        · `chcp 65001` + UTF-8-BOM 写盘 → cmd 读中文路径/中文组名不乱码
        · 可选先 taskkill 旧的 BGI（双实例会抢游戏窗口）
        · **排除日期在这里判断**：今天在列表里就直接退出（原工具在 XML 里
          "排除"是没生效的，这里是真正的跳过）
    """
    exe = str(c.get("bgi_exe") or "").strip()
    bgi_dir = str(c.get("bgi_dir") or "").strip()
    groups = [str(g).strip() for g in (c.get("groups") or []) if str(g).strip()]
    exclude = c.get("exclude_dates") or []
    lines = [
        "@echo off",
        "chcp 65001 >nul",
        "setlocal",
        "rem 由 StatGI 自动生成 —— 改了会在下次保存时被覆盖",
        "",
    ]
    # ★ 2026-10-13 用户要求：到点先把 StatGI 自己拉起来（不开 = 没人在记账）
    #   已经开着时，第二次启动只会把主窗口提到前面（单实例 ✓ 不会开两个）
    if (c or {}).get("start_self", True):
        _self_line = _self_launch_line()
        if _self_line:
            lines.append("rem ==== 先启动 StatGI（没开就没人在记账）==== ")
            lines.append(_self_line)
            lines.append("")
    if exclude:
        # 取今天日期（%date% 受区域设置影响，用 wmic/powershell 都不稳，
        # 这里用 "%~t0" 的老办法：bat 自己的修改时间 = 生成时间，不可靠。
        # 所以改用 forfiles 的日期技巧太绕 —— 直接调 PowerShell 拿 ISO 日期。）
        lines += [
            'for /f %%d in (\'powershell -NoProfile -Command '
            '"(Get-Date).ToString(\\"yyyy-MM-dd\\")"\') do set "TODAY=%%d"',
        ]
        for d in exclude:
            lines.append(f'if "%TODAY%"=="{d}" (echo 今天在排除列表（{d}），跳过 & exit /b 0)')
        lines.append("")
    if c.get("kill_existing_bgi", True):
        lines += [
            "rem 先清掉可能在跑的实例，避免双开抢窗口",
            "taskkill /IM BetterGI.exe /F >nul 2>&1",
            "timeout /t 5 /nobreak >nul",
            "",
        ]
    if bgi_dir:
        lines.append(f'cd /d "{bgi_dir}"')
    if not exe:
        lines.append("echo 没有配置要启动的程序 & pause & exit /b 1")
    elif groups:
        args = " ".join(f'"{g}"' if " " in g else g for g in groups)
        # 2026-10-13: 原来没有 start "" -> bat 会等 BGI 跑完才继续，
        # 后面的开播/挂机就得等整个 BGI 结束。加 start "" 立即继续。
        lines.append(f'start "" /D "{bgi_dir or os.path.dirname(exe)}" '
                     f'"{exe}" --startGroups {args}')
    else:
        lines.append(f'start "" /D "{bgi_dir or os.path.dirname(exe)}" "{exe}"')
    lines += build_live_bat_lines(c)
    lines += ["", "endlocal"]
    return "\r\n".join(lines) + "\r\n"


def bat_path(base=None):
    return Path(base or paths.app_dir()) / BAT_NAME


def write_bat(c, base=None):
    p = bat_path(base)
    with open(p, "w", encoding="utf-8-sig", newline="") as f:
        f.write(build_bat_text(c))
    return p


# ---------------------------------------------------------------- 拉起 / 结束



def launch_target(c):
    """直接拉起目标程序（不经过 bat，少一层黑窗）。

    返回 (成功?, 说明)
    """
    exe = str(c.get("bgi_exe") or "").strip()
    if not exe or not os.path.isfile(exe):
        return False, f"找不到要启动的程序：{exe or '（没填路径）'}"
    groups = [str(g).strip() for g in (c.get("groups") or []) if str(g).strip()]
    argv = [exe, "--startGroups"] + groups if groups else [exe]

    killed = ""
    if c.get("kill_existing_bgi", True):
        try:
            if kill_bgi():
                killed = "已结束旧进程；"
        except Exception:
            pass

    try:
        # 脱离父进程：关掉 StatGI 也不影响它
        flags = 0x00000008 | 0x00000200      # DETACHED_PROCESS | NEW_PROCESS_GROUP
        subprocess.Popen(argv, cwd=c.get("bgi_dir") or None,
                         close_fds=True, creationflags=flags)
        # 直播动作（OBS 开播 / 打开直播间）跟着一起来
        live_notes = start_live(c)
        tail = " ".join(groups)
        msg = f"{killed}已启动：{os.path.basename(exe)} --startGroups {tail}"
        if live_notes:
            msg += "；" + "；".join(live_notes)
        return True, msg
    except Exception as e:
        return False, f"启动失败：{type(e).__name__}: {e}"


def run_bat_visible(c, base=None):
    """用可见窗口跑 bat（方便看报错）——中文用 EncodedCommand 绕开编码问题"""
    import base64
    try:
        bat = write_bat(c, base)
        ps = f'cmd.exe /c ""{bat}""'
        enc = base64.b64encode(ps.encode("utf-16-le")).decode("ascii")
        subprocess.Popen(["powershell", "-NoProfile", "-EncodedCommand", enc],
                         creationflags=0x00000010)     # CREATE_NEW_CONSOLE
        return True, f"已在新窗口运行 {bat.name}"
    except Exception as e:
        return False, f"运行失败：{e}"


def open_in_explorer(path):
    try:
        p = Path(path)
        if p.is_dir():
            os.startfile(str(p))                    # noqa  Windows
        elif p.is_file():
            subprocess.Popen(["explorer", "/select,", str(p)])
        else:
            return False, f"路径不存在：{p}"
        return True, "已打开"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------- 探测








