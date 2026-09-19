# -*- coding: utf-8 -*-
"""StatGI Qt 版 · 入口

跑法：
    cd E:\\收益识别\\statgi_qt
    python main.py

（根目录那套识别模块会被直接 import，不用复制过来。）
"""
import os
import sys

# 项目根目录（识别/统计那些模块都在这儿，跟 Tk 版共用一份）。
# 注意用 append 而不是 insert(0)：本目录的 qt_*.py 必须排在前面，
# 否则一旦有同名模块，就会加载到根目录里 Tk 版的那个（之前就踩过这个坑）。
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
    # 高 DPI：Qt 自己处理，不需要 Tk 版那个 0.906 的缩放补丁
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    app = QApplication(sys.argv)
    app.setApplicationName("StatGI")

    # 窗口 / 任务栏图标
    ico = os.path.join(ROOT, "app_icon.ico")
    if os.path.exists(ico):
        app.setWindowIcon(QIcon(ico))

    # 出错也记进 data/error.log（跟 Tk 版共用同一套）
    try:
        from errlog import install_hooks
        install_hooks()
    except Exception:
        pass

    # 防止重复打开（两个程序同时识别会重复统计）。
    # 用的是跟 Tk 版**同一个**互斥体名字 —— 这样两版也不会同时跑，
    # 避免它们抢同一份 config/settings.json 互相覆盖。
    try:
        import ctypes
        ctypes.windll.kernel32.CreateMutexW(
            None, False, "GenshinIncomeTracker_SingleInstance")
        if ctypes.windll.kernel32.GetLastError() == 183:      # ERROR_ALREADY_EXISTS
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(None, "提示",
                                "程序已经在运行了。\n\n请到右下角托盘找到它。\n"
                                "（Tk 版和 Qt 版也不能同时开）")
            return 0
    except Exception:
        pass

    from qt_window import MainWindow
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
