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

HERE = os.path.dirname(os.path.abspath(__file__))
QT_DIR = os.path.join(HERE, "statgi_qt")

# 先插根目录、再插 statgi_qt，后者会排在更前面（Python 的 insert(0) 特性）。
# 顺序很重要：qt_*.py 在 statgi_qt 里，识别模块在根目录，名字不冲突但也别搞反。
for p in (HERE, QT_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

if __name__ == "__main__":
    from main import main as qt_main      # statgi_qt/main.py
    sys.exit(qt_main())
