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


def resource_file(name: str) -> Path:
    """找一个「打包内置的单个文件」（比如 app_icon.ico）

    为什么不能直接用 app_dir() / name：
    PyInstaller 会把 spec 里 datas 指定的文件放到 **_MEIPASS** 里
    （打包后就是 _internal\\ 文件夹），**不在 EXE 旁边**。
    所以 app_dir() / "app_icon.ico" 在打包版里是找不到的 ——
    托盘和任务栏就会用上兜底/默认图标。

    查找顺序：
      1. EXE 旁边（想换图标的话，直接放一个同名文件在这儿就行）
      2. 打包内置的（_MEIPASS）
      3. 源码模式：项目目录
    """
    exe_dir = app_dir()
    p = exe_dir / name
    if p.exists():
        return p
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", str(exe_dir)))
        return base / name
    return Path(__file__).resolve().parent / name
