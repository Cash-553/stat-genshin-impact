# -*- coding: utf-8 -*-
"""
OCR 引擎模块

使用 RapidOCR（内置 PP-OCRv3，识别质量经实测优于 PaddleOCR v6 on 原神小字场景）。
保留自适应阈值预处理 + 一字差纠错（在 detector 层）。

对外接口：
- recognize(frame) -> [(文字, 置信度), ...]
- recognize_boxes(frame) -> [(文字, 置信度, (x,y,w,h)), ...]
- recognize_line(frame) -> (文字, 置信度)
- extract_mora_amount(frame) -> int|None
- extract_material_count(frame) -> int
"""
import re
import threading
import cv2
import numpy as np
from rapidocr_onnxruntime import RapidOCR

# 全局共享的 RapidOCR 实例。
#
# 为什么要共享：RapidOCR 每次实例化都会**重新加载一遍模型**（十几兆）
# 并各占一份内存。以前 OcrEngine() 每 new 一个就加载一套 —— 程序里
# detector 和预热各建了一个，等于模型加载两遍、内存占两份。
# 更重要的是：预热必须和真正干活的是**同一个实例**才有意义，
# 各建各的就会「预热了一个、用的是另一个」。
_shared = None
_shared_lock = threading.Lock()


def _get_shared_ocr():
    """拿到（必要时创建）全局唯一的 RapidOCR"""
    global _shared
    if _shared is None:
        with _shared_lock:
            if _shared is None:
                ocr = RapidOCR()
                # 关掉「方向分类」(cls)。
                #
                # 它是干什么的：判断每一行文字**是不是倒着的** —— 扫描件、
                # 翻拍照片经常是倒的，所以要判断一下、转正了再认。
                #
                # 为什么我们不需要：游戏里的拾取提示、摩拉 ×200、材料名，
                # 永远是正着显示的，不可能倒过来。这一步每次都是
                # 「举起来看一眼 → 发现是正的 → 再放下」，纯属白算。
                #
                # 实测：关掉之后识别结果一字不差，快 1.3~1.8 倍。
                # 万一哪天真遇到倒着的字，只是那一行认不出来（不会认错、不会崩），
                # 把这行删掉就恢复原样。
                try:
                    ocr.use_angle_cls = False
                except Exception:
                    pass
                _shared = ocr
    return _shared


class OcrEngine:
    """轻量 OCR 封装，只在需要时才加载模型"""

    def __init__(self):
        self._ocr = None  # 延迟加载，避免程序启动变慢
        self._upscale = 3  # 预处理放大倍数（坐标还原时用）

    def _ensure(self):
        if self._ocr is None:
            self._ocr = _get_shared_ocr()

    def warm_up(self):
        """预热：启动时在后台空跑一次识别

        为什么要这个：ONNX Runtime **第一次**推理要先建内存池、做图优化，
        实测首次要 1.5~2.5 秒（之后只要几十毫秒）。
        不预热的话，用户点「开始监测」后的第一次识别会明显卡一下。

        这里拿空白图把「文字检测」和「文字识别」两个模型都跑一遍
        （空白图检测不出文本框，所以得单独再喂一次给识别模型）。

        ⚠ 空白图要按**真实输入尺寸**来：程序会先把图放大 3 倍再送进来，
        所以实际是 1000x1500 这个量级。用小图预热的话，大张量第一次
        分配内存还是要等 —— 实测小图预热后第一次真识别仍要 2 秒，
        按真实尺寸预热才真正省掉这一下。

        跑在后台线程里，不影响启动速度；失败也无所谓，忽略就行。

        注意：共享实例之后，这里预热的和 detector 用的是同一套模型，
        所以预热是真的有效的（以前各建各的，等于白热）。
        """
        try:
            self._ensure()
            # 接近真实尺寸的空白图（识别区域放大 3 倍后的量级）
            blank = np.zeros((1200, 1920, 3), dtype=np.uint8)
            self._ocr(blank)                                  # 预热：检测
            self._ocr.text_recognizer([blank[:48, :320]])     # 预热：识别
        except Exception:
            pass

    def _preprocess(self, frame_bgr):
        """
        识别前预处理：灰度 + 自适应阈值 + 放大。
        用自适应阈值（adaptiveThreshold）而非全局 Otsu，
        更擅长处理游戏里"文字被深色/浅色背景遮挡、对比度不均"的情况——每个小区域各自取阈值，
        不会再因为整帧只取一个折中阈值而把低对比度的字吞掉。
        """
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        binary = cv2.adaptiveThreshold(
            gray, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            blockSize=21,
            C=6,
        )
        _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        otsu_inv = cv2.bitwise_not(otsu)  # 转成"文字白、背景黑"与自适应一致
        combined = cv2.bitwise_or(binary, otsu_inv)
        combined = cv2.morphologyEx(combined, cv2.MORPH_OPEN, np.ones((1, 2), np.uint8))
        big = cv2.resize(combined, None, fx=self._upscale, fy=self._upscale, interpolation=cv2.INTER_NEAREST)
        return cv2.cvtColor(big, cv2.COLOR_GRAY2BGR)

    def recognize(self, frame_bgr):
        """识别图片（BGR 格式 numpy 数组），返回 [(文字, 置信度), ...]"""
        self._ensure()
        processed = self._preprocess(frame_bgr)
        result, _ = self._ocr(processed)
        lines = []
        for item in result or []:
            lines.append((item[1], float(item[2])))
        return lines

    def recognize_boxes(self, frame_bgr):
        """识别图片并返回文字位置，返回 [(文字, 置信度, (x, y, w, h)), ...]"""
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
        识别一整条文字（跳过检测，最快）。
        返回 (文字, 置信度)；识别不到返回 (None, 0.0)。
        """
        if frame_bgr is None or frame_bgr.size == 0:
            return None, 0.0
        self._ensure()
        try:
            processed = self._preprocess(frame_bgr)
            out = self._ocr.text_recognizer(processed)
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
        """从画面中提取摩拉数字（例如 +7050 → 7050），找不到返回 None"""
        lines = self.recognize(frame_bgr)
        for text, score in lines:
            m = re.search(r"\+[,\s]*([\d,]{2,})", text)
            if m:
                return int(self._clean_number(m.group(1)).replace(",", ""))
        best = None
        for text, score in lines:
            cleaned = self._clean_number(text)
            for m in re.finditer(r"(?<![x×X\d])([\d,]{3,7})(?!\d)", cleaned):
                val = int(m.group(1).replace(",", ""))
                if best is None or val > best[0]:
                    best = (val, score)
        return best[0] if best else None

    def extract_material_count(self, frame_bgr):
        """从画面中提取材料数量（例如 ×2 → 2），找不到返回 1"""
        lines = self.recognize(frame_bgr)
        for text, score in lines:
            cleaned = self._clean_number(text)
            m = re.search(r"[x×X]\s*(\d{1,2})", cleaned)
            if m:
                return int(m.group(1))
        for text, score in lines:
            cleaned = self._clean_number(text)
            for m in re.finditer(r"(?<![\d])(\d{1,2})(?![\d])", cleaned):
                return int(m.group(1))
        return 1
