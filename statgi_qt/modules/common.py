# -*- coding: utf-8 -*-
"""模块之间共用的几个小工具（探测可执行文件、脱离父进程启动）。

放到这里是为了让每个模块文件夹**自带**它需要的工具 —— 这样删掉一个模块
文件夹时，不会把别的模块还要用的东西一起带走。
"""
import os
import subprocess


def first_existing(paths):
    """给一串候选路径，返回第一个真实存在的文件（都没有返回 ""）"""
    for p in paths:
        try:
            if p and os.path.isfile(p):
                return p
        except Exception:
            continue
    return ""


def scan_dir_for(root, pattern, rel):
    """在 `root\<名字含 pattern 的目录>` 下找 `rel`"""
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


def start_detached(argv, cwd=None):
    """脱离父进程启动（关掉本程序也不影响它）"""
    flags = 0x00000008 | 0x00000200      # DETACHED_PROCESS | NEW_PROCESS_GROUP
    return subprocess.Popen(list(argv), cwd=cwd or None, close_fds=True,
                            creationflags=flags)


def open_with_default(url):
    """交给系统默认程序打开（没指定浏览器时用）"""
    os.startfile(str(url))               # noqa: S606 - 用户自己填的网址


def bat_start_line(exe, args=(), cwd=None):
    """生成 bat 里一行 `start "" /D ... "exe" args`"""
    d = cwd if cwd is not None else os.path.dirname(str(exe))
    a = (" " + " ".join(f'"{x}"' if " " in str(x) else str(x)
                       for x in (args or ()))) if args else ""
    if d:
        return f'start "" /D "{d}" "{exe}"{a}'
    return f'start "" "{exe}"{a}'
