# -*- coding: utf-8 -*-
"""统一的出错记录。

为什么要单独搞一个：
- 打包成 exe 之后没有控制台，print 出去的报错**看不见**；
- 代码里大量 `except Exception: pass` 会把问题彻底吞掉
  （之前「自定义背景图没效果」查了很久，就是因为异常被吞了）；
- 界面回调、后台线程里抛的异常，Tk 默认也不会告诉你。

用法：
    from errlog import log_exc, install_hooks
    log_exc("玻璃背景")            # 在 except 里记一笔
    install_hooks()                # 启动时装一次，兜住所有漏网的异常

日志写到 data/error.log，同一条错误最多每 30 秒记一次，避免刷屏。
"""
import io
import os
import sys
import time
import traceback

_LOG_NAME = "error.log"
_seen = {}
_last_clean = 0.0


def _log_path():
    try:
        import paths
        p = paths.app_dir() / "data"
    except Exception:
        p = None
    if p is None:
        return None
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return p / _LOG_NAME


def _write(text):
    p = _log_path()
    if p is None:
        return
    try:
        with io.open(str(p), "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except Exception:
        pass
    try:
        print(text)
    except Exception:
        pass


def _trim(path, keep=200):
    """日志太大就留最近 keep 行，避免无限增长"""
    try:
        with io.open(str(path), "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        if len(lines) > keep * 2:
            with io.open(str(path), "w", encoding="utf-8") as f:
                f.writelines(lines[-keep:])
    except Exception:
        pass


def log_exc(where=""):
    """记一笔异常（在 except 里调用）。同一个位置 30 秒内只记一次。"""
    global _last_clean
    try:
        now = time.time()
        key = where or "?"
        if now - _seen.get(key, 0.0) < 30:
            return
        _seen[key] = now
        tb = traceback.format_exc()
        if tb and tb.strip() != "NoneType: None":
            _write("[%s] %s\n%s" % (time.strftime("%Y-%m-%d %H:%M:%S"), key, tb.rstrip()))
        else:
            _write("[%s] %s（没有异常信息）" % (time.strftime("%Y-%m-%d %H:%M:%S"), key))
        if now - _last_clean > 600:
            _last_clean = now
            p = _log_path()
            if p is not None:
                _trim(p)
    except Exception:
        pass


def install_hooks():
    """把「界面上没人管的异常」「后台线程里的异常」都记到文件里"""
    # 1) Tkinter 回调里抛出来的
    try:
        import tkinter
        _orig = tkinter.Tk.report_callback_exception

        def _tk_hook(self, exc, val, tb):
            try:
                _write("[%s] 界面回调异常\n%s" % (
                    time.strftime("%Y-%m-%d %H:%M:%S"),
                    "".join(traceback.format_exception(exc, val, tb)).rstrip()))
            except Exception:
                pass
            try:
                _orig(self, exc, val, tb)
            except Exception:
                pass

        tkinter.Tk.report_callback_exception = _tk_hook
    except Exception:
        pass

    # 2) 后台线程里抛出来的
    try:
        import threading

        def _th_hook(args):
            try:
                _write("[%s] 后台线程异常（%s）\n%s" % (
                    time.strftime("%Y-%m-%d %H:%M:%S"),
                    getattr(args.thread, "name", "?"),
                    "".join(traceback.format_exception(args.exc_type, args.exc_value,
                                                       args.exc_traceback)).rstrip()))
            except Exception:
                pass

        threading.excepthook = _th_hook
    except Exception:
        pass

    # 3) 主线程漏网的
    try:
        def _sys_hook(exc, val, tb):
            try:
                _write("[%s] 未捕获异常\n%s" % (
                    time.strftime("%Y-%m-%d %H:%M:%S"),
                    "".join(traceback.format_exception(exc, val, tb)).rstrip()))
            except Exception:
                pass

        sys.excepthook = _sys_hook
    except Exception:
        pass
