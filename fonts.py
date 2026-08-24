# -*- coding: utf-8 -*-
"""
字体共享模块

检测系统可用的字体，统一返回 FONT 供所有界面使用。
优先微软雅黑（Microsoft YaHei UI，以前的字体，中文显示最稳），
没有时回退 Segoe UI Variable / Segoe UI。
"""
try:
    import tkinter as tk
    _probe = tk.Tk()
    _probe.withdraw()
    _fams = set(_probe.tk.call("font", "families"))
    _probe.destroy()
except Exception:
    _fams = set()

if "Microsoft YaHei UI" in _fams:
    FONT = "Microsoft YaHei UI"
elif "微软雅黑" in _fams:
    FONT = "微软雅黑"
elif "Segoe UI Variable" in _fams:
    FONT = "Segoe UI Variable"
elif "Segoe UI" in _fams:
    FONT = "Segoe UI"
else:
    FONT = "Microsoft YaHei UI"
