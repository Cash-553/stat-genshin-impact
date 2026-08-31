# -*- coding: utf-8 -*-
"""
AI 主界面判断模块（ONNX Runtime 推理，不依赖 torch）

用 MobileNetV3-Small 训练并转换为 ONNX 的模型判断当前画面是否是"游戏主界面"。
模型文件：models/main_ui_model.onnx（可替换，重新转换后覆盖即可）

ONNX 模型内部已封装完整逻辑（转换脚本 _开发测试_new/convert_to_onnx.py）：
  输入 [1,3,216,384] 归一化张量 -> MobileNetV3-Small 特征提取 -> 全局平均池化(576维)
  -> L2 归一化 -> 与主界面平均特征点积 -> 输出标量相似度
预处理（ToTensor + Normalize）在本模块用 numpy 完成。

判定逻辑：
- 单帧相似度 >= 阈值(0.70) → 主界面
- 离开缓冲：从"识别到非主界面"的那一帧开始，往后推 2.5 秒内，
  只要再识别到主界面，就认为仍在主界面（短暂离开不算离开）。
  只有持续超过 2.5 秒都识别不到主界面，才真正判定为离开主界面。
"""
import sys
import time
from pathlib import Path

import cv2
import numpy as np

import paths

IMG_H, IMG_W = 216, 384
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def _model_path():
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", str(paths.app_dir()))
        p = Path(base) / "models" / "main_ui_model.onnx"
        if p.exists():
            return p
    p = Path(__file__).resolve().parent / "models" / "main_ui_model.onnx"
    return p


class MainUiDetector:
    """AI 主界面判断器（ONNX Runtime 推理，含 2.5 秒离开缓冲）"""

    def __init__(self):
        self._sess = None
        self._input_name = None
        self._threshold = 0.70
        self._leave_grace = 2.5   # 秒：离开主界面的缓冲时间
        self._last_main_time = 0.0  # 最近一次判定为主界面的时间
        self._last_pred = True      # 最近一次是否在主界面
        self.last_sim = 0.0         # 最近一次单帧相似度（供日志/调试查看）

    def _ensure(self):
        """惰性加载 onnxruntime Session（线程安全足够：首次调用加载一次）"""
        if self._sess is not None:
            return True
        try:
            import onnxruntime as ort
            mp = _model_path()
            if not mp.exists():
                return False
            self._sess = ort.InferenceSession(str(mp), providers=["CPUExecutionProvider"])
            self._input_name = self._sess.get_inputs()[0].name
            return True
        except Exception:
            return False

    def _preprocess(self, frame_bgr):
        """BGR 帧 (H,W,3) -> [1,3,216,384] 归一化 float32"""
        img = cv2.resize(frame_bgr, (IMG_W, IMG_H), interpolation=cv2.INTER_LINEAR)
        img = img.astype(np.float32) / 255.0
        img = (img - MEAN) / STD
        img = img.transpose(2, 0, 1)[None]  # 1,3,216,384
        return np.ascontiguousarray(img, dtype=np.float32)

    def _predict_single(self, frame_bgr):
        """返回 (相似度, 是否主界面)"""
        try:
            x = self._preprocess(frame_bgr)
            out = self._sess.run(None, {self._input_name: x})[0]
            sim = float(np.asarray(out).reshape(-1)[0])
            return sim, sim >= self._threshold
        except Exception:
            return 0.0, True  # 出错时保守当作主界面（不阻断识别）

    def in_main_ui(self, frame):
        """
        判断当前是否在主界面（带 2.5 秒离开缓冲）。
        返回 True=在主界面（可以识别），False=不在主界面（应暂停识别）。
        """
        now = time.time()
        if not self._ensure():
            return True  # 模型不可用：不阻断（保持原有行为）

        sim, is_main = self._predict_single(frame)
        self.last_sim = sim

        if is_main:
            self._last_main_time = now
            self._last_pred = True
            return True

        # 非主界面：检查离开缓冲
        # 从"第一次识别到非主界面"开始计时，若 2.5 秒内之前一直是主界面，则仍算主界面
        if now - self._last_main_time <= self._leave_grace:
            # 还在 2.5 秒缓冲内（最近刚离开主界面，短暂离开不算离开）
            return True

        self._last_pred = False
        return False

    def close(self):
        self._sess = None
