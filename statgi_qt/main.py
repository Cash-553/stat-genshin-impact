# -*- coding: utf-8 -*-
"""StatGI Qt 版 · 入口

跑法：
    cd E:\\收益识别\\statgi_qt
    python main.py

（根目录那套识别模块会被直接 import，不用复制过来。）
"""
import os
import sys

# 项目根目录（识别/统计那些模块都在这儿）。
# 注意用 append 而不是 insert(0)：本目录的 qt_*.py 必须排在前面，
# 否则一旦有同名模块，就可能加载到根目录里的那个（之前就踩过这个坑）。
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.append(ROOT)

try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication
except ImportError:
    print("=" * 56)
    print("  还差一个库：PySide6")
    print("      pip install PySide6")
    print("=" * 56)
    sys.exit(1)




def _ipc_log(msg):
    """单实例相关日志。写 <程序目录>/日志/单实例.log，并打到 stderr。"""
    try:
        import paths
        d = paths.app_dir() / "日志"
        d.mkdir(parents=True, exist_ok=True)
        import datetime
        with open(d / "单实例.log", "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
    except Exception as e:
        try:
            print("[单实例][日志写不进去]", e, flush=True)
        except Exception:
            pass
    try:
        print("[单实例]", msg, flush=True)
    except Exception:
        pass


def _raise_by_window():
    """硬兜底：**不用 socket**，直接把"同一个 exe 的另一个窗口"提到最前。

    做法：枚举所有顶层窗口 → 看窗口属于哪个进程 → 那个进程的 exe 路径
    跟本程序是不是同一个 → 是就恢复并置前。
    这条路不依赖 Qt 的网络模块，可靠性更高（用户反馈 socket 那条没生效）。
    """
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        my_exe = str(Path(sys.executable).resolve()).lower()

        found = []

        def _cb(hwnd, _lparam):
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                h = kernel32.OpenProcess(0x1000, False, pid.value)  # QUERY_LIMITED
                if not h:
                    return True
                try:
                    buf = ctypes.create_unicode_buffer(1024)
                    size = wintypes.DWORD(1024)
                    if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                        if str(buf.value).lower() == my_exe:
                            found.append(hwnd)
                finally:
                    kernel32.CloseHandle(h)
            except Exception:
                pass
            return True

        CB = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows(CB(_cb), 0)
        if not found:
            _ipc_log("硬兜底：没找到同程序的窗口")
            return False
        hwnd = found[0]
        user32.ShowWindow(hwnd, 9)            # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
        _ipc_log(f"硬兜底：已把窗口 {hwnd} 置前")
        return True
    except Exception as e:
        _ipc_log(f"硬兜底失败：{type(e).__name__}: {e}")
        return False


SINGLE_SOCKET = "StatGI_SingleInstance_v095"


def _activate_existing(timeout_ms=900):
    """第二个实例：通知已经在跑的那个"把窗口呼出来"。成功返回 True。"""
    try:
        from PySide6.QtNetwork import QLocalSocket
        s = QLocalSocket()
        s.connectToServer(SINGLE_SOCKET)
        if not s.waitForConnected(timeout_ms):
            _ipc_log(f"第二个实例连不上（{SINGLE_SOCKET}）：{s.errorString()}")
            return False
        _ipc_log(f"第二个实例已连上（{SINGLE_SOCKET}），发出 show")
        s.write(b"show")
        s.flush()
        s.waitForBytesWritten(600)
        s.disconnectFromServer()
        return True
    except Exception:
        return False


def _raise_window(win):
    """把主窗口从托盘/最小化里恢复并提到最前"""
    from PySide6.QtCore import Qt
    try:
        win.showNormal()
        if win.windowState() & Qt.WindowMinimized:
            win.setWindowState(win.windowState() & ~Qt.WindowMinimized)
        win.raise_()
        win.activateWindow()
    except Exception:
        pass


def _serve_activate(win):
    """第一个实例：开个本地 socket 等着，第二个实例一连上就呼出窗口。"""
    try:
        from PySide6.QtNetwork import QLocalServer
        QLocalServer.removeServer(SINGLE_SOCKET)     # 清掉上次残留
        srv = QLocalServer(win)
        if not srv.listen(SINGLE_SOCKET):
            _ipc_log(f"监听失败（{SINGLE_SOCKET}）：{srv.errorString()}")
            return None
        _ipc_log(f"第一个实例开始监听（{SINGLE_SOCKET}）")

        def _on_conn():
            c = srv.nextPendingConnection()
            if c is None:
                return
            try:
                c.waitForReadyRead(200)
                c.readAll()
                c.disconnectFromServer()
            except Exception:
                pass
            _raise_window(win)

        srv.newConnection.connect(_on_conn)
        return srv
    except Exception:
        return None


def main():
    # 界面缩放（用户设置里的 ui_scale）——
    # ⚠ 必须赶在 **QApplication 建出来之前** 设 `QT_SCALE_FACTOR`：
    #   Qt 只在建 App 那一刻读一次，之后再改没用（所以设置里写了"重启后生效"）。
    try:
        import config_manager
        _sc = float(config_manager.load_settings().get("ui_scale", 1.0) or 1.0)
        if abs(_sc - 1.0) > 0.001:
            os.environ["QT_SCALE_FACTOR"] = f"{_sc:g}"
    except Exception:
        pass

    # 高 DPI：交给 Qt 自己处理
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    # ---- 自检开关（2026-10-13）：STATGI_SELFTEST=1 时跑探测、写结果、退出 ----
    # 用途：打包版"探测得到吗"不再靠肉眼点按钮，直接看 自检.txt
    try:
        import os as _os
        if _os.environ.get("STATGI_SELFTEST") == "1":
            _lines = []
            try:
                import svc_autostart as _A
                import modules as _M
                _lines.append("BGI   探测: " + repr(_A.detect_bgi()))
                _live = _M.load_logic("live")
                _hang = _M.load_logic("hang")
                _lines.append("OBS   探测: " + repr(_live.detect_obs() if _live else ""))
                _lines.append("Chrome探测: " + repr(_hang.detect_chrome() if _hang else ""))
                _b, _e = _A.detect_bgi()
                _lines.append("BGI   组名: " + repr(_A.bgi_groups(_b, _e)))
                for _n in ("bgi", "live", "hang"):
                    _lines.append(f"logic {_n} 加载: "
                                  + str(_A._load_module_logic(_n) is not None))
            except Exception as _e2:
                import traceback
                _lines.append("探测出错: " + repr(_e2))
                _lines.append(traceback.format_exc())
            try:
                import modules as _M
                _lines.append("模块清单: "
                              + repr([m["key"] for m in _M.load_all()]))
                _lines.append("搜索目录: "
                              + repr([str(x) for x in _M.roots()]))
            except Exception as _e3:
                _lines.append("模块清单出错: " + repr(_e3))
            try:
                import paths as _pa
                _out = _pa.app_dir() / "自检.txt"
                _out.write_text("\n".join(_lines), encoding="utf-8")
                print("[自检] 已写", _out, flush=True)
            except Exception as _e4:
                print("[自检] 写文件失败:", _e4, flush=True)
            print("\n".join(_lines), flush=True)
            return 0
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setApplicationName("StatGI")

    # 窗口 / 任务栏图标
    # 用 paths.resource_file()，不能自己拼路径：
    # 打包后 app_icon.ico 在 _internal\ 里（= _MEIPASS），不在 EXE 旁边；
    # 而且打包版没有 __file__ 可依赖，ROOT 算出来是错的。
    try:
        from paths import resource_file
        ico = resource_file("app_icon.ico")
        if ico.exists():
            app.setWindowIcon(QIcon(str(ico)))
    except Exception:
        pass

    # 出错也记进 data/日志/报错/
    try:
        from errlog import install_hooks
        install_hooks()
    except Exception:
        pass

    # 防止重复打开（两个程序同时识别会重复统计）。
    # 互斥体名字沿用旧版那个。改成新的会让新旧两版能同时跑，
    # 那样它们会抢同一份 config/settings.json 互相覆盖 —— 所以别改。
    try:
        import ctypes
        ctypes.windll.kernel32.CreateMutexW(
            None, False, "GenshinIncomeTracker_SingleInstance")
        if ctypes.windll.kernel32.GetLastError() == 183:      # ERROR_ALREADY_EXISTS
            # 用户 2026-10-13：第二次双击图标不要弹"已经在运行"，而是**直接把
            # 已经在跑的那个主窗口呼出来**（可能被最小化或被收进托盘了）。
            if _activate_existing():
                return 0
            # 万一对面是旧版本（没开这个接收口），才退回原来的提示
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(None, "提示",
                                "程序已经在运行了。\n\n请到右下角托盘找到它。")
            return 0
    except Exception:
        pass

    from qt_window import MainWindow

    # 一次性重置材料库。
    #
    # 老版本开着「自动登记新材料」，OCR 认错的名字也被记进材料库了，
    # 攒了一堆错的。materials_db.LIB_VERSION 加一，所有老用户下次启动
    # 自动清一次，只留内置那份材料名单。
    #
    # ⚠ 必须放在建窗口之前 —— Detector 一建实例就会 load_materials()
    #   把名字读进内存，先清完再读，否则这一轮用的还是旧库。
    try:
        import config_manager
        import materials_db
        _s = config_manager.load_settings()
        if materials_db.migrate_library(_s):
            config_manager.save_settings(_s)
            print("[材料库] 已按新版本重置为内置列表")
    except Exception:
        pass

    # 清一下上次自动更新留下的临时文件（下载分卷 / 新版本解压出来的东西 /
    # 备份目录 / 更新.bat）。更新脚本是先启动本程序、再自己退出的，
    # 所以到这里它已经干完活了，删掉是安全的。
    try:
        import qt_updater
        qt_updater.cleanup()
    except Exception:
        pass

    # 更新时 `robocopy` 会整个跳过 icons\（免得冲掉用户自己导入的图标），
    # 所以这里把新版本自带的图标补上：
    #   · 三个 slot + mora/artifact 永远按新版本覆盖（外观基线）
    #   · 其余只在缺失时补，不覆盖同名文件 —— 用户的图得以保留
    try:
        import icons_lib
        icons_lib.sync_bundled_icons()
    except Exception:
        pass

    win = MainWindow()
    win.show()

    # 识别日志：**新开一个日志文件**（一次运行一个，放进 data/识别日志/），
    # 并写一段抬头（时间 + 当前识别名单）——
    # 这样出了"认不出来"的问题时，能先确认当时用的是哪份名单
    try:
        import detect_log
        detect_log.session_start(win.settings)
    except Exception:
        pass

    # 启动预热：在**后台线程**里把 OCR 模型加载好、空跑一次。
    #
    # 为什么要：ONNX Runtime 第一次推理要先建内存池、做图优化，
    # 实测首次要 1.5~2.5 秒。不预热的话，用户点「开始监测」之后
    # 第一次识别会明显卡一下（现在虽然也会显示「正在加载识别模型…」，
    # 但那是点下去之后才开始的）。
    #
    # 放后台 + daemon：不拖慢启动，也不影响程序能不能关掉。
    # 失败就失败，识别时会自己再加载一遍，不影响功能。
    try:
        import threading

        def _warm():
            try:
                from ocr_engine import OcrEngine
                OcrEngine().warm_up()
            except Exception:
                pass

        threading.Thread(target=_warm, daemon=True, name="ocr-warmup").start()
    except Exception:
        pass

    # 启动后自动查一次更新（后台线程，两个渠道都试）。
    # 放到 show() 之后、延后 1.5 秒再开始 —— 让界面先画出来，别抢启动那几秒。
    from PySide6.QtCore import QTimer
    # 2026-10-13：**必须真的调用**！之前只写了函数定义没调用，
    # 第一个实例根本没开监听 → 第二次双击只能弹"请到托盘找它"。
    _serve_activate(win)
    QTimer.singleShot(1500, win.start_update_check)

    # ★ 2026-10-13：关机 / 注销 / 被结束进程时，也要把这一段监测**收尾记账**。
    #   原来只有「点 ✕ 退出主程序」和「停止监测」会写记录；直接关机、注销、
    #   任务管理器结束进程都会丢掉这一段挂机的收益。
    #   Windows 结束会话时 Qt 会发 aboutToQuit —— 只要系统给我们一点时间，
    #   这里就能把记录补上。（拔电源这种硬断电救不了，任何程序都一样。）
    try:
        def _finalize_on_quit():
            try:
                win._quitting = True          # 别在关机时弹「本次小结」
            except Exception:
                pass
            try:
                if win.state.monitoring or getattr(win.state, "paused", False):
                    win.state.stop()          # stop() 里会 _record_session()
            except Exception:
                pass

        app.aboutToQuit.connect(_finalize_on_quit)
    except Exception:
        pass

    rc = app.exec()

    # 识别日志：记一行关闭
    try:
        import detect_log
        detect_log.session_end(win.settings)
    except Exception:
        pass
    return rc


if __name__ == "__main__":
    sys.exit(main())
