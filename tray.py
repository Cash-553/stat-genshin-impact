# -*- coding: utf-8 -*-
"""
系统托盘模块
程序最小化后，在任务栏右下角显示一个小图标。
点击托盘图标可以：显示主窗口 / 退出程序。
"""
import os
import queue
import sys
import threading
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

import theme


def _icon_file():
    """找到树叶图标文件 app_icon.ico（和主程序同一个图标）"""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", str(Path(sys.executable).parent))
        p = Path(base) / "app_icon.ico"
        if p.exists():
            return p
    p = Path(__file__).resolve().parent / "app_icon.ico"
    return p if p.exists() else None


def _make_tray_image():
    """生成托盘图标：优先用树叶图标（与软件图标一致），找不到再画一个圆点方块"""
    try:
        ico = _icon_file()
        if ico:
            img = Image.open(ico).convert("RGBA")
            img = img.resize((64, 64), Image.LANCZOS)
            # pystray 需要 RGB；铺深色底再合成，避免透明区域发黑
            bg = Image.new("RGB", (64, 64), theme.BG)
            bg.paste(img, (0, 0), img)
            return bg
    except Exception:
        pass
    img = Image.new("RGB", (64, 64), theme.BG)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([4, 4, 60, 60], radius=14, fill=theme.CARD)
    d.ellipse([22, 22, 42, 42], outline=theme.ACCENT, width=5)
    return img


class Tray:
    """托盘图标。动作通过队列传给主窗口（tkinter 不能跨线程直接操作）"""

    def __init__(self):
        self.q = queue.Queue()
        menu = pystray.Menu(
            # default=True：双击托盘图标也能呼出主窗口（单击会弹出菜单）
            pystray.MenuItem("显示主窗口", lambda: self.q.put("show"), default=True),
            pystray.MenuItem("退出程序", lambda: self.q.put("exit")),
        )
        self.icon = pystray.Icon(
            "genshin_income_tracker",
            _make_tray_image(),
            "StatGI",
            menu,
        )

    def start(self):
        threading.Thread(target=self.icon.run, daemon=True).start()

    def stop(self):
        try:
            self.icon.stop()
        except Exception:
            pass

    def poll(self):
        """取出待处理的动作列表（主窗口每秒调用几次）"""
        items = []
        while True:
            try:
                items.append(self.q.get_nowait())
            except queue.Empty:
                break
        return items
