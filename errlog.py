# -*- coding: utf-8 -*-
"""统一的出错记录。

为什么要单独搞一个：
- 打包成 exe 之后没有控制台，print 出去的报错**看不见**；
- 代码里大量 `except Exception: pass` 会把问题彻底吞掉
  （之前「自定义背景图没效果」查了很久，就是因为异常被吞了）；
- 界面回调、后台线程里抛的异常，Qt 默认也不会告诉你。

用法：
    from errlog import log_exc, install_hooks
    log_exc("玻璃背景")            # 在 except 里记一笔（要在 except 块里调）
    install_hooks()                # 启动时装一次，兜住所有漏网的异常

## 日志放哪（2026-09-29 规范过）

    所有日志统一收进 `data/日志/`，**按类型分文件夹、按天分文件**，
    不再全糊在一个文件里：

        data/日志/
            报错/  报错_20260929.log         ← 本模块（同一条错误 30 秒去重）
            识别/  识别_20260929_040512.log  ← detect_log（每次运行一个）
            诊断/  诊断_20260929.log         ← Detector 的调试输出（默认关）

    按天分文件的好处：出问题只要看当天的那个文件，不用在几千行里翻。

⚠ 老位置的两个文件（`data/error.log`、`data/识别日志.log`）**不删** ——
  那是用户的历史数据，留着就是了，程序不再往里写。
"""
import io
import sys
import time
import traceback

# 所有日志的根目录（相对 data/）
LOG_ROOT_NAME = "日志"
ERROR_DIR_NAME = "报错"

_seen = {}
_last_clean = 0.0

# 单个报错日志的软上限：超过就把旧行砍掉（按天分文件之后一般到不了）
_MAX_LINES = 4000


def log_root():
    """所有日志的根目录 `data/日志/`；取不到就返回 None。"""
    try:
        import paths
        return paths.app_dir() / "data" / LOG_ROOT_NAME
    except Exception:
        return None


def _sub_dir(name):
    """取 `data/日志/<name>/`，顺便建出来。"""
    root = log_root()
    if root is None:
        return None
    try:
        d = root / name
        d.mkdir(parents=True, exist_ok=True)
        return d
    except Exception:
        return None


def _log_path():
    """今天的报错日志：`data/日志/报错/报错_YYYYMMDD.log`"""
    d = _sub_dir(ERROR_DIR_NAME)
    if d is None:
        return None
    return d / ("报错_%s.log" % time.strftime("%Y%m%d"))


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


def _trim(path):
    """日志太大就留最近一半，避免单日文件无限增长"""
    try:
        with io.open(str(path), "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        if len(lines) > _MAX_LINES:
            with io.open(str(path), "w", encoding="utf-8") as f:
                f.writelines(lines[-_MAX_LINES // 2:])
    except Exception:
        pass


def log_exc(where=""):
    """记一笔异常（**必须在 except 块里调用**）。同一个位置 30 秒内只记一次。

    `where` 是一句人话，说明"在哪出的错"（比如「识别循环」「qt_window 公告」）。
    """
    global _last_clean
    try:
        now = time.time()
        key = where or "?"
        if now - _seen.get(key, 0.0) < 30:
            return
        _seen[key] = now
        tb = traceback.format_exc()
        if tb and tb.strip() != "NoneType: None":
            _write("[%s] %s\n%s" % (time.strftime("%Y-%m-%d %H:%M:%S"), key,
                                    tb.rstrip()))
        else:
            _write("[%s] %s（没有异常信息）" % (time.strftime("%Y-%m-%d %H:%M:%S"),
                                              key))
        if now - _last_clean > 600:
            _last_clean = now
            p = _log_path()
            if p is not None:
                _trim(p)
    except Exception:
        pass


def log_msg(where="", text=""):
    """记一条**普通消息**（不是异常）。

    给「识别连续出错」这类需要留证据、但异常只抛一次的场景用 ——
    异常对象在下一轮就用不了了，得当场把文字记下来。
    同一位置 5 秒内只记一次，避免刷屏。
    """
    try:
        now = time.time()
        key = "msg:" + (where or "?")
        if now - _seen.get(key, 0.0) < 5:
            return
        _seen[key] = now
        _write("[%s] %s：%s" % (time.strftime("%Y-%m-%d %H:%M:%S"),
                                where or "消息", text))
    except Exception:
        pass


def install_hooks():
    """把「界面上没人管的异常」「后台线程里的异常」都记到文件里"""
    # 1) Qt 的消息/异常
    # 为什么需要：Python 异常如果发生在 Qt 的槽函数里，不一定走 sys.excepthook，
    # 而打包成窗口版后 stderr 是被丢掉的 —— 不钩的话等于什么都没记到，
    # 出了问题只能看到「程序闪退了」。QMessageHandler 是 Qt 唯一的出口。
    try:
        from PySide6.QtCore import qInstallMessageHandler, QtMsgType

        # 已知无害、但会刷屏的 Qt 警告 —— 记下来只会让人以为程序出问题了
        _BENIGN = (
            "QFont::setPointSize",      # Qt 内部对无效字号的抱怨，不影响显示
        )

        def _qt_hook(mode, ctx, msg):
            try:
                if any(b in str(msg) for b in _BENIGN):
                    return
                if mode in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg,
                            QtMsgType.QtFatalMsg):
                    where = ""
                    try:
                        if ctx is not None and ctx.file:
                            where = f"（{ctx.file}:{ctx.line}）"
                    except Exception:
                        pass
                    _write("[%s] Qt 消息%s\n%s" % (
                        time.strftime("%Y-%m-%d %H:%M:%S"), where, msg))
            except Exception:
                pass
        qInstallMessageHandler(_qt_hook)
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
