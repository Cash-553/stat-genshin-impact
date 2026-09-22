# -*- coding: utf-8 -*-
"""StatGI · 打包入口

跟 statgi_qt/main.py 是同一件事，只是多做了两件打包需要的事：
  1. 把 statgi_qt 目录放进搜索路径 —— 这样 PyInstaller 在打包时
     也能找到 qt_window / qt_pages 这些模块（它们在子目录里，
     不加路径的话分析不到，打出来的包会 import 失败）
  2. 冻结后（打包成 exe）不做多余的路径猜测：PyInstaller 已经把
     所有模块和 datas 解到 sys._MEIPASS 了，而它在 sys.path 里。

打包配置是根目录的 StatGI.spec。
（v0.9 起只有 Qt 一个版本了，旧的那套 Tk 界面已经删掉。）
"""
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
QT_DIR = os.path.join(HERE, "statgi_qt")

# 先插根目录、再插 statgi_qt，后者会排在更前面（Python 的 insert(0) 特性）。
# 顺序很重要：qt_*.py 在 statgi_qt 里，识别模块在根目录，名字不冲突但也别搞反。
for p in (HERE, QT_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)


# ============================================================
#  启动日志（默认不写，排查打包问题时才开）
#
#  为什么需要：打包版是 console=False，**没有任何输出**。启动阶段一崩
#  （或者被单实例检测挡住直接返回 0），用户那边就是"双击没反应"，
#  而 data\error.log 是进到主窗口之后才装的钩子，抓不到这个阶段。
#
#  用法：设环境变量 STATGI_STARTUP_LOG=1 再启动，就会写
#  exe 旁边的 data\startup.log。
#
#  ⚠ 目录要按 **exe 旁边** 算，不能用 __file__ —— 冻结后 __file__ 指向
#    _internal\，日志会写到 _internal\data\ 里去（踩过）。
# ============================================================
def _log(msg):
    import os as _os
    if _os.environ.get("STATGI_STARTUP_LOG") != "1":
        return
    try:
        import paths
        d = paths.app_dir() / "data"
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "startup.log", "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


if __name__ == "__main__":
    import time
    _log(f"--- 启动 {time.strftime('%Y-%m-%d %H:%M:%S')} ---")
    _log(f"  冻结={getattr(sys, 'frozen', False)}  "
         f"_MEIPASS={getattr(sys, '_MEIPASS', '(无)')}")
    _log(f"  python={sys.version.split()[0]}")
    try:
        from main import main as qt_main      # statgi_qt/main.py
    except Exception:
        _log("  ✗ import main 失败：\n" + traceback.format_exc())
        raise
    try:
        rc = qt_main()
        _log(f"  main() 返回 {rc}")
        sys.exit(rc)
    except SystemExit as e:
        _log(f"  SystemExit: {e}")
        raise
    except Exception:
        _log("  ✗ main() 抛异常：\n" + traceback.format_exc())
        raise
