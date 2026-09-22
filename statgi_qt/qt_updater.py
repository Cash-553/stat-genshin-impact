# -*- coding: utf-8 -*-
"""StatGI · 自动更新

做四件事：下载分卷 → 拼回整包 → 校验 → 解压到临时目录，
然后写一个「更新.bat」交给外部去替换文件。

为什么替换要交给外部的 bat：
    程序没法替换正在运行的自己（Windows 会锁住 StatGI.exe）。
    所以流程是：程序先退出 → bat 把新文件搬过去 → bat 再把程序打开。
    这是所有软件更新都在用的做法。

安全措施：
  · 下载完先校验 SHA256，对不上就删掉临时文件、原样不动
  · 解压和替换都**跳过 config\\ 和 data\\** —— 用户的设置和收益数据不能动
  · 替换前先把旧文件备份到 _backup\\，bat 替换失败会自动还原
  · 全程出错都只是「更新没做成」，不影响现在这个版本继续用
"""
import hashlib
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile

import paths

TIMEOUT = 30           # 单个分卷最多等几秒（大文件要久一点）
UA = {"User-Agent": "StatGI"}

# 更新过程中要跳过的目录（用户数据，绝不能覆盖）
KEEP_DIRS = ("config", "data")


def work_dir():
    """下载和解压都放这儿"""
    return paths.app_dir() / "data" / "_update"


def _human(n):
    try:
        n = float(n)
    except Exception:
        return "?"
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{u}"
        n /= 1024
    return f"{n:.1f}TB"


def _download(url, dest, on_progress=None, done_bytes=0, total_bytes=0):
    """下载一个文件，边下边报进度"""
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        with open(dest, "wb") as f:
            while True:
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if on_progress:
                    on_progress(done_bytes + got, total_bytes or (done_bytes + total))
    return dest


def _sha256(path, on_progress=None, done=0, total=0):
    h = hashlib.sha256()
    read = 0
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
            read += len(b)
            if on_progress and size:
                on_progress(done + read, total or size)
    return h.hexdigest()


# ------------------------------------------------------------
def update_info_from(ver_json):
    """从 version.json 里取出更新信息

    格式（生成更新包.py 会自动写）：
        "update": {
          "size": 150138346,
          "sha256": "…",
          "sources": [
            {"label": "Gitee（国内快）", "parts": ["url1", "url2"]},
            {"label": "GitHub", "parts": ["url"]}
          ]
        }
    没有这一段就返回 None（说明这个版本没准备自动更新）。
    """
    if not isinstance(ver_json, dict):
        return None
    u = ver_json.get("update")
    if not isinstance(u, dict):
        return None
    srcs = u.get("sources")
    if not isinstance(srcs, list) or not srcs:
        return None
    good = [s for s in srcs
            if isinstance(s, dict) and isinstance(s.get("parts"), list)
            and s["parts"]]
    if not good:
        return None
    return {"size": int(u.get("size") or 0),
            "sha256": str(u.get("sha256") or "").strip().lower(),
            "sources": good}


def prepare(update, on_log=None, on_progress=None):
    """下载 + 合并 + 校验 + 解压。成功返回解压出来的目录，失败抛异常。

    on_log(str)                  进度文字
    on_progress(done, total)     字节进度
    """
    def log(s):
        if on_log:
            on_log(s)

    wd = work_dir()
    # 先清干净
    import shutil
    shutil.rmtree(wd, ignore_errors=True)
    (wd / "parts").mkdir(parents=True, exist_ok=True)
    (wd / "new").mkdir(parents=True, exist_ok=True)

    total = int(update.get("size") or 0)

    last_err = None
    for src in update["sources"]:
        label = str(src.get("label") or "下载源")
        parts = [str(x) for x in src.get("parts") or [] if str(x).strip()]
        if not parts:
            continue
        try:
            log(f"正在从 {label} 下载（共 {len(parts)} 个文件）…")
            # 每个分卷大概多大：总大小 / 分卷数
            per = int(total / len(parts)) if (total and len(parts)) else 0
            merged = wd / "package.zip"
            with open(merged, "wb") as out:
                for i, url in enumerate(parts, 1):
                    fn = wd / "parts" / f"part{i}"
                    log(f"   第 {i}/{len(parts)} 个…")
                    _download(url, str(fn),
                              on_progress=on_progress,
                              done_bytes=(i - 1) * per,
                              total_bytes=total)

                    # 下一个分卷之前，先把进度推上去（这个分卷下完了）
                    if on_progress and per:
                        on_progress(min(total, i * per), total)

                    with open(fn, "rb") as f:
                        shutil.copyfileobj(f, out, 1024 * 1024)
                    try:
                        fn.unlink()          # 拼完就删，省地方
                    except Exception:
                        pass

            # 校验
            if update.get("sha256"):
                log("校验文件完整性…")
                got = _sha256(str(merged), on_progress=on_progress,
                              done=0, total=total or os.path.getsize(merged))
                if got.lower() != update["sha256"]:
                    log(f"   ✗ 校验不通过（下载可能不完整）")
                    last_err = "文件校验不通过"
                    try:
                        merged.unlink()
                    except Exception:
                        pass
                    continue
                log("   ✓ 校验通过")
            else:
                log("   （没有校验值，跳过校验）")

            # 解压
            log("正在解压…")
            with zipfile.ZipFile(str(merged)) as z:
                names = z.namelist()
                # 安全检查：别让压缩包里的路径跑出目录（zip slip）
                for n in names:
                    p = os.path.normpath(n)
                    if p.startswith("..") or os.path.isabs(p):
                        raise Exception(f"压缩包里有个可疑路径：{n}")
                z.extractall(str(wd / "new"))
            log(f"   解压出 {len(names)} 个文件")
            try:
                merged.unlink()
            except Exception:
                pass
            return wd / "new"

        except Exception as e:
            last_err = f"{label} 失败：{type(e).__name__}: {e}"
            log(f"   ✗ {last_err}，换下一个源…")
            continue

    raise Exception(last_err or "所有下载源都失败了")


# ------------------------------------------------------------
UPDATE_BAT = "更新.bat"


def _oem_encoding():
    """取系统控制台用的代码页（中文 Windows = 936 / GBK）

    为什么要这个：cmd.exe 读 .bat 是按**控制台代码页**解析的。
      · 文件按 UTF-8 写 → cmd 按 GBK 读 → 中文乱码，路径也会读错
      · 文件按 GBK 写，但脚本开头 chcp 65001 → 一样会乱 ✗
        （这个坑真踩过：chcp 切了之后连 robocopy 的路径都读错，
          导致替换失败、走了还原流程）
    正确做法：**文件按系统 OEM 代码页写，并且 chcp 切到同一个值**。
    这样不是中文系统也能正常工作（英文系统 OEM 是 437）。
    """
    try:
        import ctypes
        cp = int(ctypes.windll.kernel32.GetOEMCP())
        if cp > 0:
            return f"cp{cp}", cp
    except Exception:
        pass
    return "cp936", 936


def write_updater(new_dir):
    """写好「更新.bat」—— 它负责等程序退出后替换文件、再打开程序

    返回 bat 的路径。
    """
    app = paths.app_dir()
    bat = app / UPDATE_BAT
    enc, cp = _oem_encoding()
    # bat 里用相对路径（%~dp0），整个文件夹挪位置也不影响
    content = f'''@echo off
chcp {cp} >nul
title StatGI 正在更新
cd /d "%~dp0"

echo.
echo   StatGI 正在更新，请不要关掉这个窗口…
echo.

rem ---- 1) 等主程序完全退出（最多等 30 秒，不行就强关）----
set /a n=0
:wait
tasklist /fi "imagename eq StatGI.exe" 2>nul | find /i "StatGI.exe" >nul
if not errorlevel 1 (
    set /a n+=1
    if %n% gtr 30 (
        echo   主程序没有自己关掉，正在强制关闭…
        taskkill /f /im StatGI.exe >nul 2>nul
        timeout /t 2 /nobreak >nul
        goto go
    )
    timeout /t 1 /nobreak >nul
    goto wait
)

:go

rem ---- 2) 备份旧文件（除了用户数据）----
if exist "_backup" rd /s /q "_backup"
echo   正在备份旧版本…
robocopy "." "_backup" /E /XD config data icons _backup /NFL /NDL /NJH /NJS >nul

rem ---- 3) 把新文件搬过去（跳过 config、data 和 icons）----
rem ⚠ icons 整个跳过：用户能自己往 icons\\ 里导入图标，
rem   直接覆盖会把人家导入的图删掉。
rem   新版本自带的图标由主程序启动时补齐（icons_lib.sync_bundled_icons）。
echo   正在替换文件…
robocopy "{new_dir}" "." /E /XD config data icons _backup /NFL /NDL /NJH /NJS >nul
if errorlevel 8 goto failed

echo   完成！
goto done

:failed
echo.
echo   ✗ 替换失败，正在还原旧版本…
robocopy "_backup" "." /E /XD config data icons _backup /NFL /NDL /NJH /NJS >nul
echo   已还原，你的软件还能正常用。
echo.
pause
goto done

:giveup
rem （已不再跳到这里 —— 等不到就 taskkill 了。留着是防止 goto 写错时炸掉）
exit /b

:done
rem ---- 4) 清理 + 重新打开 ----
rd /s /q "data\\_update" 2>nul
rd /s /q "_backup" 2>nul
echo.
echo   正在重新打开 StatGI…
start "" "%~dp0StatGI.exe"
echo.
echo   好了，这个窗口 3 秒后自动关闭。
timeout /t 3 /nobreak >nul
exit /b
'''
    # ⚠ 必须按 OEM 代码页写盘，不能写 UTF-8（见 _oem_encoding 的说明）
    with open(bat, "w", encoding=enc, errors="replace", newline="\r\n") as f:
        f.write(content)
    return bat


def launch_updater(bat_path):
    """启动更新 bat（新开一个**可见**的控制台窗口，本程序退出后它继续跑）

    ⚠ 这里踩过坑：一开始用的是 DETACHED_PROCESS（脱离控制台），
    结果 bat 在「没有控制台」的状态下跑 —— 里面的 tasklist 管道、
    start 都行为异常，用户那边什么都看不到，更新完也不会重新打开。
    正确做法是 CREATE_NEW_CONSOLE：给它一个自己的窗口，
    bat 里的 echo 用户能看到，出问题也知道卡在哪一步。
    """
    CREATE_NEW_CONSOLE = 0x00000010
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    try:
        subprocess.Popen(
            ["cmd", "/c", str(bat_path)],
            cwd=str(paths.app_dir()),
            creationflags=CREATE_NEW_CONSOLE | CREATE_NEW_PROCESS_GROUP,
            close_fds=True)
        return True
    except Exception:
        # 退一步：用 start 打开
        try:
            subprocess.Popen(["cmd", "/c", "start", "", str(bat_path)],
                             cwd=str(paths.app_dir()))
            return True
        except Exception:
            return False


def force_quit_soon(seconds=3.0):
    """兜底：过几秒把本进程强杀掉

    更新时必须让位给更新脚本 —— 万一 Qt 的事件循环或某个后台线程
    卡住了（窗口还留在屏幕上、exec 不返回），更新脚本就会一直等，
    最后放弃。所以启动一个看门狗线程，到点直接 os._exit。

    设置和统计都是**改一下立刻存盘**的，所以强杀不会丢数据。
    """
    import threading

    def _die():
        time.sleep(seconds)
        os._exit(0)

    threading.Thread(target=_die, daemon=True).start()


def cleanup():
    """把上次更新留下的临时文件清掉（程序启动时调一次）"""
    import shutil
    app = paths.app_dir()
    for p in (work_dir(), app / "_backup"):
        try:
            shutil.rmtree(p, ignore_errors=True)
        except Exception:
            pass
    try:
        bat = app / UPDATE_BAT
        if bat.exists():
            bat.unlink()
    except Exception:
        pass
