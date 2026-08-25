# -*- coding: utf-8 -*-
"""
OCR 引擎模块
封装 rapidocr，专门用于读取掉落提示里的数字：
- 摩拉数量（例如 +7050）
- 材料数量（例如 ×2）
"""
import re
import cv2
import numpy as np
from rapidocr_onnxruntime import RapidOCR


class OcrEngine:
    """轻量 OCR 封装，只在需要时才加载模型"""

    def __init__(self):
        self._ocr = None  # 延迟加载，避免程序启动变慢
        self._upscale = 3  # 预处理放大倍数（坐标还原时用）

    def _ensure(self):
        if self._ocr is None:
            self._ocr = RapidOCR()

    def _preprocess(self, frame_bgr):
        """
        识别前预处理：灰度 + 自适应阈值 + 放大。
        用自适应阈值（adaptiveThreshold）而非全局 Otsu，
        更擅长处理游戏里"文字被深色/浅色背景遮挡、对比度不均"的情况——每个小区域各自取阈值，
        不会再因为整帧只取一个折中阈值而把低对比度的字吞掉。
        """
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        # 自适应阈值：局部邻域内文字(亮)和背景(暗)分开
        binary = cv2.adaptiveThreshold(
            gray, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            blockSize=21,
            C=6,
        )
        # 与全局 Otsu 结合兜底：两种都能识别时保留，避免自适应在某些文字上失效
        _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        otsu_inv = cv2.bitwise_not(otsu)  # 转成"文字白、背景黑"与自适应一致
        combined = cv2.bitwise_or(binary, otsu_inv)
        # 降噪：去掉细小的孤立噪点
        combined = cv2.morphologyEx(combined, cv2.MORPH_OPEN, np.ones((1, 2), np.uint8))
        big = cv2.resize(combined, None, fx=self._upscale, fy=self._upscale, interpolation=cv2.INTER_NEAREST)
        return cv2.cvtColor(big, cv2.COLOR_GRAY2BGR)

    def recognize(self, frame_bgr):
        """
        识别图片（BGR 格式 numpy 数组）
        返回 [(文字, 置信度), ...]

        预处理：灰度 + Otsu 二值化 + 放大 2 倍（参考 BetterGI），
        游戏里的小字（如 ×2）也能被识别。
        """
        self._ensure()
        processed = self._preprocess(frame_bgr)
        result, _ = self._ocr(processed)
        lines = []
        for item in result or []:
            lines.append((item[1], float(item[2])))
        return lines

    def recognize_boxes(self, frame_bgr):
        """
        识别图片并返回文字位置（用于自动提取图标）
        返回 [(文字, 置信度, (x, y, w, h)), ...]，坐标为原始图片坐标
        """
        self._ensure()
        processed = self._preprocess(frame_bgr)
        result, _ = self._ocr(processed)
        lines = []
        for item in result or []:
            box = item[0]  # 4 个点（在放大图上，坐标除以倍数还原）
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            x, y = int(min(xs) / self._upscale), int(min(ys) / self._upscale)
            w, h = int((max(xs) - min(xs)) / self._upscale), int((max(ys) - min(ys)) / self._upscale)
            lines.append((str(item[1]), float(item[2]), (x, y, w, h)))
        return lines

    def recognize_line(self, frame_bgr):
        """
        照搬 BetterGI：把一整条文字直接送进识别模型（跳过文字检测），最快。
        输入：裁剪好的单行文字条（BGR numpy 数组）。
        返回 (文字, 置信度)；识别不到返回 (None, 0.0)。
        """
        if frame_bgr is None or frame_bgr.size == 0:
            return None, 0.0
        self._ensure()
        try:
            processed = self._preprocess(frame_bgr)
            out = self._ocr.text_recognizer(processed)
            # 返回格式通常是 ([('文字', 分数)], 耗时) 或直接列表
            items = out[0] if isinstance(out, tuple) else out
            if items:
                text, score = items[0]
                return str(text), float(score)
        except Exception:
            pass
        # 兜底：走完整管线
        try:
            lines = self.recognize(frame_bgr)
            if lines:
                return str(lines[0][0]), float(lines[0][1])
        except Exception:
            pass
        return None, 0.0

    # ---------- 数字提取 ----------

    @staticmethod
    def _clean_number(text):
        """纠正 OCR 常见的数字误读（O→0, l→1 等）"""
        return (
            text.replace("O", "0").replace("o", "0")
            .replace("l", "1").replace("I", "1")
            .replace("S", "5").replace("s", "5")
        )

    def extract_mora_amount(self, frame_bgr):
        """
        从画面中提取摩拉数字（例如 +7050 → 7050）
        找不到返回 None
        """
        lines = self.recognize(frame_bgr)
        # 方式1：找 "+数字" 模式（游戏显示"摩拉 +7050"）
        for text, score in lines:
            m = re.search(r"\+[,\s]*([\d,]{2,})", text)
            if m:
                return int(self._clean_number(m.group(1)).replace(",", ""))
        # 方式2：找独立的 3~7 位数字（可能加号没被识别出来）
        best = None
        for text, score in lines:
            cleaned = self._clean_number(text)
            for m in re.finditer(r"(?<![x×X\d])([\d,]{3,7})(?!\d)", cleaned):
                val = int(m.group(1).replace(",", ""))
                if best is None or val > best[0]:
                    best = (val, score)
        return best[0] if best else None

    def extract_material_count(self, frame_bgr):
        """
        从画面中提取材料数量（例如 ×2 → 2）
        找不到时返回 1（游戏默认掉落 1 个）
        """
        lines = self.recognize(frame_bgr)
        # 方式1：找 "×数字" 或 "x数字" 模式
        for text, score in lines:
            cleaned = self._clean_number(text)
            m = re.search(r"[x×X]\s*(\d{1,2})", cleaned)
            if m:
                return int(m.group(1))
        # 方式2：找单独的 1~2 位数字
        for text, score in lines:
            cleaned = self._clean_number(text)
            for m in re.finditer(r"(?<![\d])(\d{1,2})(?![\d])", cleaned):
                return int(m.group(1))
        return 1
