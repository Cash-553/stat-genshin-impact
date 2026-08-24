# -*- coding: utf-8 -*-
"""
演示模式
不用打开游戏，也能体验完整的识别统计流程。

原理：程序自己生成"模拟掉落提示"画面（摩拉+7050、材料×2、圣遗物），
然后走和真实监测完全相同的识别引擎，统计数字会自己涨起来。
"""
import numpy as np
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

import detector as detector_mod

DEMO_ICONS_DIR = Path(__file__).parent / "_demo_icons"


def prepare_demo_icons():
    """生成模拟图标（和真实截图一样放进 icons 文件夹）"""
    DEMO_ICONS_DIR.mkdir(exist_ok=True)
    specs = [
        ("mora", (255, 200, 60), "circle"),        # 金色圆形 = 摩拉
        ("artifact", (255, 120, 200), "diamond"),  # 粉色菱形 = 圣遗物
        ("破损的面具", (200, 60, 60), "triangle"),  # 红色三角 = 面具
        ("史莱姆凝液", (80, 200, 120), "circle"),   # 绿色圆形 = 史莱姆
    ]
    for name, color, shape in specs:
        p = DEMO_ICONS_DIR / (name + ".png")
        if not p.exists():
            img = Image.new("RGB", (64, 64), (26, 26, 42))
            d = ImageDraw.Draw(img)
            r = 10
            if shape == "circle":
                d.ellipse([r, r, 64 - r, 64 - r], fill=color)
            elif shape == "diamond":
                d.polygon([(32, r), (64 - r, 32), (32, 64 - r), (r, 32)], fill=color)
            elif shape == "triangle":
                d.polygon([(32, r), (r, 64 - r), (64 - r, 64 - r)], fill=color)
            img.save(p)


class DemoCapture:
    """假的屏幕捕捉器：按剧本依次返回模拟画面"""

    def __init__(self, region):
        self.region = region
        self._script = self._build_script()
        self._idx = 0
        self._tick_in_frame = 0

    def _frame(self, icon_name=None, text=None):
        w, h = self.region["w"], self.region["h"]
        img = Image.new("RGB", (w, h), (26, 26, 42))
        if icon_name:
            icon = Image.open(DEMO_ICONS_DIR / (icon_name + ".png"))
            img.paste(icon, (40, 30))
        if text:
            font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 34)
            ImageDraw.Draw(img).text((130, 32), text, fill=(255, 255, 255), font=font)
        return np.array(img)[:, :, ::-1]

    def _build_script(self):
        """剧本：(画面, 持续几次检测)。每次检测间隔约0.5秒"""
        return [
            (self._frame(), 4),                              # 空
            (self._frame("mora", "摩拉 +7050"), 8),          # 摩拉出现
            (self._frame(), 4),                              # 消失
            (self._frame("破损的面具", "破损的面具 ×2"), 8),   # 材料出现
            (self._frame(), 4),                              # 消失
            (self._frame("artifact", "幸运儿银冠 ×1"), 8),    # 圣遗物出现（文字识别）
            (self._frame(), 4),                              # 消失
            (self._frame("史莱姆凝液", "史莱姆凝液 ×1"), 8),   # 材料出现
            (self._frame(), 4),                              # 消失
        ]

    def grab(self, region):
        frame, reps = self._script[self._idx]
        self._tick_in_frame += 1
        if self._tick_in_frame >= reps:
            self._tick_in_frame = 0
            self._idx = (self._idx + 1) % len(self._script)
        return frame

    def close(self):
        pass


def create_demo_detector(region, stats, settings=None):
    """创建一个跑演示画面的检测器（接口和真实检测器完全一样）"""
    prepare_demo_icons()
    det = detector_mod.Detector(region, DEMO_ICONS_DIR, settings, stats=stats)
    det.capture = DemoCapture(region)
    return det
