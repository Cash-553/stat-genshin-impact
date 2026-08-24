# -*- coding: utf-8 -*-
"""
设置管理模块
负责读写 config/settings.json
（识别区域、各种选项都保存在这里）
"""
import json
from pathlib import Path
import paths

# 项目根目录（打包成 EXE 后自动变成 EXE 所在文件夹）
BASE_DIR = paths.app_dir()
CONFIG_DIR = BASE_DIR / "config"
SETTINGS_FILE = CONFIG_DIR / "settings.json"

# 默认设置（第一次运行时使用）
DEFAULT_SETTINGS = {
    "region": None,      # 识别区域 {"x":.., "y":.., "w":.., "h":..}，屏幕绝对坐标
    "monitor": 1,        # 显示器编号（暂时固定用主显示器）
    "api_port": 8765,    # 直播数据接口端口（OBS 浏览器源用）
    "event_end_window": 1.5,   # 事件去重窗口（秒）：提示消失多久后算新事件
    "change_threshold": 4.0,   # 画面变化检测灵敏度（越小越敏感）
    "safety_interval": 1.5,    # 无变化时的保底检测间隔（秒）
    "tick_interval": 50,       # 检测间隔（毫秒，默认50）
    "ocr_interval": 250,       # 文字识别节流（毫秒，OCR最多多久一次）
    "change_level": "中",      # 画面变化灵敏度（界面显示用）
    # 识别开关（文字识别：想统计什么就开什么）
    "enable_mora": True,             # 识别摩拉
    "enable_material": True,         # 识别怪物素材
    "enable_artifact": True,         # 识别圣遗物（狗粮）
    "auto_register_material": True,  # 遇到不认识的材料自动登记到材料库
    "save_debug": False,           # 自动保存诊断截图（已停用：识别完不留文件；手动诊断仍可用）
    "close_behavior": "ask",       # 点 ✕ 时：ask=每次询问 / tray=最小化到托盘 / exit=直接退出
    # 外观设置（改后重启程序生效；预设名见 theme.py）
    "bg_color": "经典深黑",          # 背景色：预设名 或 #RRGGBB
    "accent_color": "经典蓝",        # 强调色：预设名 或 #RRGGBB
    "bg_image": "",                 # 自定义背景图片路径（空=纯色背景）
    "sidebar_glass": True,          # 左侧栏毛玻璃效果
    # 横向统计条（直播间小窗口）：三个格子的图标文件（icons 文件夹里，内置默认）
    "stat_bar": {
        "slot1": "_bar_slot1.png",   # 摩拉（内置）
        "slot2": "_bar_slot2.png",   # 材料（内置）
        "slot3": "_bar_slot3.png",   # 狗粮（内置）
        "always_on_top": True,       # 是否置顶
    },
}


def load_settings():
    """读取设置；文件不存在或损坏时返回默认设置"""
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            merged = dict(DEFAULT_SETTINGS)
            merged.update(data)
            # 迁移旧版设置：close_to_tray(布尔) → close_behavior(三态)
            if "close_to_tray" in data and "close_behavior" not in data:
                merged["close_behavior"] = "tray" if data["close_to_tray"] else "exit"
            return merged
        except Exception:
            return dict(DEFAULT_SETTINGS)
    return dict(DEFAULT_SETTINGS)


def save_settings(settings):
    """保存设置到 config/settings.json"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
