# -*- coding: utf-8 -*-
"""
路径工具模块

程序有两种运行方式：
1. 开发模式（python app.py）     → 文件夹就在项目目录里
2. 打包成 EXE 后（双击运行）      → 文件夹必须在 EXE 旁边

这个模块负责统一找到正确的位置，
保证 icons / data / config 文件夹始终在"程序旁边"，方便你自己修改。

注意：打包版里 icons 文件夹只有一种情况会不同——
EXE 旁边没有 icons 文件夹时，退回使用打包内置的图标（_MEIPASS/icons）。
"""
import sys
from pathlib import Path


def app_dir() -> Path:
    """返回程序所在的主文件夹（数据/配置放这里，EXE旁）"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_dir() -> Path:
    """返回资源根目录（内部含 icons 子文件夹）：
    - 打包成 EXE 后：EXE 所在文件夹（用户可放自定义 icons）
    - 开发模式：项目目录
    """
    return app_dir()


def icons_dir() -> Path:
    """返回 icons 文件夹（图标图片所在处）：
    - 开发模式：项目目录/icons
    - 打包版：优先 EXE 旁 icons（用户可自定义、可替换），
      没有则退回打包内置的图标（_MEIPASS/icons）
    """
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        if (exe_dir / "icons").exists():
            return exe_dir / "icons"
        # 打包内置图标
        base = getattr(sys, "_MEIPASS", str(exe_dir))
        return Path(base) / "icons"
    return Path(__file__).resolve().parent / "icons"
