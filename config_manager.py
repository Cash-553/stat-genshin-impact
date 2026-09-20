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

# ---- 档位表（界面下拉框用，两个版本共用这一份）----
# 名字统一成 4 档：性能 / 标准 / 省电 / 极致省电
#   文字识别频率：数值是毫秒，**越小越频繁**（越频繁越吃 CPU）
#   画面变化灵敏度：数值是变化阈值，**越小越灵敏**（越灵敏越吃 CPU）
# 两处名字一致，用户不用分别记两套叫法。
OCR_LEVELS = [("性能", 100), ("标准", 150), ("省电", 250), ("极致省电", 500)]
CHANGE_LEVELS = [("性能", 1.0), ("标准", 2.0), ("省电", 4.0), ("极致省电", 8.0)]

DEFAULT_OCR_LEVEL = "标准"          # = 150ms
DEFAULT_CHANGE_LEVEL = "标准"       # = 2.0

# 默认设置（第一次运行时使用）
DEFAULT_SETTINGS = {
    "region": None,      # 识别区域 {"x":.., "y":.., "w":.., "h":..}，屏幕绝对坐标
    "monitor": 1,        # 显示器编号（暂时固定用主显示器）
    "api_port": 8765,    # 直播数据接口端口（OBS 浏览器源用）
    "event_end_window": 1.5,   # 事件去重窗口（秒）：提示消失多久后算新事件
    "change_threshold": 2.0,   # 画面变化检测灵敏度（越小越敏感）=「标准」
    "safety_interval": 1.5,    # 无变化时的保底检测间隔（秒）
    "tick_interval": 50,       # 检测间隔（毫秒，默认50）
    "ocr_interval": 150,       # 文字识别节流（毫秒）=「标准」
    "change_level": "标准",    # 画面变化灵敏度（界面显示用；真正生效的是 change_threshold）
    # 识别开关（文字识别：想统计什么就开什么）
    "enable_mora": True,             # 识别摩拉
    "enable_material": True,         # 识别怪物素材
    "enable_artifact": True,         # 识别圣遗物（狗粮）
    "auto_register_material": True,  # 遇到不认识的材料自动登记到材料库
    "only_foreground": True,       # 只在原神窗口在前台时识别（切到其他应用停止识别）
    # 开发者选项（默认隐藏，不采集，不影响普通用户）
    "developer_mode": False,       # 开发者模式（开启后显示开发者选项）
    "dataset_enabled": False,      # AI 样本采集开关
    "dataset_path": "",            # 样本保存目录（空=默认 %LOCALAPPDATA%/StatGI/dataset）
    "save_debug": False,           # 自动保存诊断截图（已停用：识别完不留文件；手动诊断仍可用）
    "close_behavior": "ask",       # 点 ✕ 时：ask=每次询问 / tray=最小化到托盘 / exit=直接退出
    # 外观设置（改后重启程序生效；预设名见 theme.py）
    "bg_color": "经典深黑",          # 背景色：预设名 或 #RRGGBB
    "accent_color": "经典蓝",        # 强调色：预设名 或 #RRGGBB
    "bg_image": "",                 # 自定义背景图片路径（空=纯色背景）
    "bg_dim": 0.0,                  # 背景图压暗程度（0~0.6，照片类背景图看不清字时用）
    "sidebar_glass": True,          # 左侧栏是否模糊（需要先设置背景图片）
    "panel_opacity": 0.5,           # 面板（卡片/侧边栏/按钮）透明度：0=全透明，1=不透明
    # 横向统计条（直播间小窗口）：三个格子的图标文件（icons 文件夹里，内置默认）
    "stat_bar": {
        "slot1": "_bar_slot1.png",   # 摩拉（内置）
        "slot2": "_bar_slot2.png",   # 材料（内置）
        "slot3": "_bar_slot3.png",   # 狗粮（内置）
        "always_on_top": True,       # 是否置顶
        "opacity": 1.0,              # 统计条透明度（0.2~1.0，1.0=不透明）
        "show_slot1": True,          # 是否显示「摩拉」格
        "show_slot2": True,          # 是否显示「材料」格
        "show_slot3": True,          # 是否显示「狗粮」格
    },
    "rollover_hour": 0,              # 换日时间（0=自然日；4=凌晨4点换日）
    "rollover_enabled": True,        # 换日刷新数据总开关（关掉就一直累着，不换日）
    "obs_api_enabled": True,         # 直播数据接口总开关（OBS 那个，改了立刻生效）
    "hotkey": "关闭",                # 全局热键：开始/停止监测
    "hotkey_bar": "关闭",            # 全局热键：显示/隐藏统计条
    "hotkey_home": "关闭",           # 全局热键：把主窗口叫回来
    "update_channel": "auto",        # 检测更新走哪个渠道：auto / gitee / github
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
