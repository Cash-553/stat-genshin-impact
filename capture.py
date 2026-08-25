# -*- coding: utf-8 -*-
"""
屏幕捕捉模块
用 mss 快速抓取指定区域，只抓框选的那一小块，不扫描全屏。
"""
import ctypes
from ctypes import wintypes

import numpy as np
import mss


def find_game_window():
    """
    自动查找原神游戏窗口（像 BetterGI 一样不用手动框选）。
    返回 {"x":.., "y":.., "w":.., "h":..}（窗口客户区屏幕坐标），找不到返回 None。
    """
    user32 = ctypes.windll.user32
    dwmapi = ctypes.windll.dwmapi
    best = [None]

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, lparam):
        # ctypes 回调绝不能抛异常（会导致进程 fail-fast 闪退），全部 try 包住
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            n = user32.GetWindowTextLengthW(hwnd)
            if n <= 0:
                return True
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            title = buf.value
            # 排除我们自己的窗口和其它工具
            if any(k in title for k in ("挂机收益", "BetterGI", "BetterGenshin", "BetterGenshinImpact")):
                return True
            # 窗口类名（原神是 Unity 引擎，类名 UnityWndClass）
            cls_buf = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(hwnd, cls_buf, 64)
            cls = cls_buf.value
            # 标题匹配：国服/国际服/云原神
            is_game = ("原神" in title and "米哈游启动器" not in title) \
                or "genshin" in title.lower() or "yuanshen" in title.lower() \
                or "云原神" in title or "yunyuanshen" in title.lower() \
                or ("原" in title and cls == "UnityWndClass") \
                or ("Genshin" in title and cls == "UnityWndClass")
            if not is_game:
                return True
            # 用 DWM 拿窗口客户区（不含标题栏）
            rect = wintypes.RECT()
            dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect))
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            if w < 400 or h < 300:
                return True  # 太小，不是主窗口
            area = w * h
            if best[0] is None or area > best[0][0]:
                best[0] = (area, {"x": rect.left, "y": rect.top, "w": w, "h": h})
        except Exception:
            pass
        return True

    user32.EnumWindows(cb, 0)
    if best[0]:
        return best[0][1]
    return None


def is_genshin_foreground():
    """
    判断当前前台（活动）窗口是否是原神游戏窗口。
    用于：切到别的应用时不截图识别，只在原神在前台时才识别。
    返回 True=是原神在前台，False=不是（或判断失败）。
    """
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False
        # 前台窗口标题
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        title = buf.value
        # 前台窗口类名
        cls_buf = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls_buf, 64)
        cls = cls_buf.value
        # 排除我们自己的工具和其它
        if any(k in title for k in ("StatGI", "原神挂机", "BetterGI", "BetterGenshin", "BetterGenshinImpact")):
            return False
        # 与 find_game_window 相同的匹配规则
        is_game = ("原神" in title and "米哈游启动器" not in title) \
            or "genshin" in title.lower() or "yuanshen" in title.lower() \
            or "云原神" in title or "yunyuanshen" in title.lower() \
            or ("原" in title and cls == "UnityWndClass") \
            or ("Genshin" in title and cls == "UnityWndClass")
        return is_game
    except Exception:
        return False


class ScreenCapture:
    """屏幕捕捉器"""

    def __init__(self):
        self._sct = mss.MSS()

    def grab(self, region):
        """
        抓取一个区域，返回 BGR 3通道 numpy 数组
        region: {"x":.., "y":.., "w":.., "h":..} 屏幕绝对坐标
        """
        mss_region = {
            "left": region["x"],
            "top": region["y"],
            "width": region["w"],
            "height": region["h"],
        }
        shot = self._sct.grab(mss_region)
        # mss 返回 BGRA 4通道，去掉 Alpha 转成 BGR 3通道（否则模板匹配会报错）
        return np.array(shot)[:, :, :3]

    def close(self):
        try:
            self._sct.close()
        except Exception:
            pass
