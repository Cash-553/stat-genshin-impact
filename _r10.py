# -*- coding: utf-8 -*-
"""用程序真实的预处理路径，测优化前后"""
import io
import os
import sys
import time
import glob
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
ROOT = r'E:\收益识别'
os.chdir(ROOT)
sys.path.insert(0, ROOT)

import cv2
import numpy as np


def imread_u(path):
    return cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)


from ocr_engine import OcrEngine
from rapidocr_onnxruntime import RapidOCR

eng = OcrEngine()
paths = []
for d in ('_开发测试', 'data'):
    for ext in ('*.png', '*.jpg', '*.bmp'):
        paths += glob.glob(os.path.join(ROOT, d, '**', ext), recursive=True)
paths = [p for p in paths if os.path.getsize(p) > 5000][:2]

for p in paths:
    img = imread_u(p)
    if img is None:
        continue
    pre = eng._preprocess(img)
    print(f'=== {os.path.basename(p)} ===')
    print(f'   原图   {img.shape[1]}x{img.shape[0]}')
    print(f'   预处理 {pre.shape[1]}x{pre.shape[0]}   ← 放大 3 倍后')

    for name, kw in (('① 现在（RapidOCR 默认限短边736）', None),
                     ('② 改成限长边 960', ('max', 960)),
                     ('③ 改成限长边 640', ('max', 640))):
        ocr = RapidOCR()
        if kw:
            for op in ocr.text_detector.preprocess_op:
                if hasattr(op, 'limit_type'):
                    op.limit_type, op.limit_side_len = kw
        # 预热
        for _ in range(8):
            ocr(pre)
        ts = []
        res = None
        for _ in range(10):
            t0 = time.perf_counter()
            res, _ = ocr(pre)
            ts.append((time.perf_counter() - t0) * 1000)
        ts.sort()
        print(f'   {name:32s} 中位 {ts[len(ts)//2]:7.1f} ms  '
              f'{len(res) if res else 0} 行')
    print()
