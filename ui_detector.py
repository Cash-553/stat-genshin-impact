# -*- coding: utf-8 -*-
"""
界面状态检测（判断当前游戏是否在主世界锄地界面）

原理：主世界锄地界面没有返回键/关闭键；打开其他界面（菜单/背包/角色等）时，
固定位置会出现返回键（左上角）或关闭键（右上角）。用模板匹配检测这两个按钮，
检测到任一 → 判定为非主界面。

模板：buttons/back_tpl.png（返回）、buttons/close_tpl.png（关闭）
位置（1080p 基准，等比缩放）：
- 返回键：左上角 (15,15)-(80,80)
- 关闭键：右上角 (1810,15)-(1870,80)
"""
import sys
from pathlib import Path

import cv2
import numpy as np

import paths

# 模板位置（1080p 基准坐标，识别时按 h/1080 等比缩放）
BACK_REGION = (15, 15, 80, 80)     # (x0,y0,x1,y1) 左上角返回键
CLOSE_REGION = (1810, 15, 1870, 80)  # 右上角关闭键
MATCH_THRESHOLD = 0.70  # 相关系数 ≥ 该值判定为检测到按钮


def _buttons_dir():
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", str(paths.app_dir()))
        p = Path(base) / "buttons"
        if p.exists():
            return p
    p = Path(__file__).resolve().parent / "buttons"
    return p


class UiDetector:
    """判断当前画面是否为游戏主界面（无返回/关闭键）"""

    def __init__(self):
        self._back_tpl = None
        self._close_tpl = None

    def _ensure_tpl(self):
        if self._back_tpl is not None:
            return
        bd = _buttons_dir()
        # 用 PIL 加载（cv2 对中文路径支持差，会产生 warning）
        try:
            from PIL import Image
            back_p = bd / "back_tpl.png"
            if back_p.exists():
                arr = np.array(Image.open(str(back_p)).convert("RGB"))
                self._back_tpl = arr[:, :, ::-1]  # RGB->BGR
            close_p = bd / "close_tpl.png"
            if close_p.exists():
                arr = np.array(Image.open(str(close_p)).convert("RGB"))
                self._close_tpl = arr[:, :, ::-1]
        except Exception:
            pass

    def _match(self, frame, tpl, region):
        """在指定区域做模板匹配，返回最大相关系数"""
        if tpl is None or frame is None:
            return -1.0
        h, w = frame.shape[:2]
        s = h / 1080.0
        x0, y0, x1, y1 = region
        x0, y0 = int(x0 * s), int(y0 * s)
        x1, y1 = int(x1 * s), int(y1 * s)
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(w, x1), min(h, y1)
        sub = frame[y0:y1, x0:x1]
        th, tw = tpl.shape[:2]
        if sub.shape[0] < th or sub.shape[1] < tw:
            return -1.0
        try:
            res = cv2.matchTemplate(sub, tpl, cv2.TM_CCOEFF_NORMED)
            return float(res.max())
        except Exception:
            return -1.0

    def in_main_ui(self, frame):
        """
        判断当前画面是否在主界面（无返回/关闭键）。
        返回 True=主界面（可以识别），False=打开了其他界面（应暂停识别）。
        """
        self._ensure_tpl()
        if self._back_tpl is None and self._close_tpl is None:
            return True  # 模板缺失，不拦截（保持原有行为）
        # 检测到任一按钮 → 非主界面
        if self._back_tpl is not None:
            if self._match(frame, self._back_tpl, BACK_REGION) >= MATCH_THRESHOLD:
                return False
        if self._close_tpl is not None:
            if self._match(frame, self._close_tpl, CLOSE_REGION) >= MATCH_THRESHOLD:
                return False
        return True
