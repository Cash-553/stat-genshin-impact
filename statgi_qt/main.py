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


def main():
    # 高 DPI：交给 Qt 自己处理
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

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

    # 出错也记进 data/error.log
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

    # 识别日志：写一段抬头（时间 + 当前识别名单），这样出了"认不出来"的
    # 问题时，能先确认当时用的是哪份名单
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
    QTimer.singleShot(1500, win.start_update_check)

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
