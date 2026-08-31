# -*- coding: utf-8 -*-
"""
本地 AI 样本采集器（开发者选项，默认关闭）

用于积累 GAMEPLAY / NON_GAMEPLAY 训练样本，为后续 AI 分类模型训练做准备。
本阶段只采集，不训练 AI。

原则：
- 默认关闭，不影响普通用户、不影响现有拾取识别
- 截图全部留在本地，不上传、不联网、不进 Git
- 截图处理（缩放/压缩/去重/写入）尽量后台，不阻塞主识别
- 数据集最大 100 MB 硬限制
"""
import json
import os
import threading
import time
from pathlib import Path

import numpy as np
import cv2

DEFAULT_PATH = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "StatGI" / "dataset"
MAX_SIZE_MB = 100          # 数据总上限
CLEAN_AT_MB = 90           # 接近上限开始清理
SAVE_W = 384               # 目标宽
SAVE_H = 216               # 目标高（16:9）
JPEG_QUALITY = 75
COOLDOWN_SECONDS = 1.5     # 采集冷却
PHASH_DIFF_THRESHOLD = 6   # pHash 汉明距离，超过视为不同


def _phash(bgr):
    """感知哈希（dHash 简化）：返回 64bit 哈希值"""
    small = cv2.resize(bgr, (9, 8), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    diff = gray[:, 1:] > gray[:, :-1]  # 水平相邻比较
    bits = diff.flatten().astype(np.uint8)
    h = 0
    for i, b in enumerate(bits):
        h |= (int(b) << i)
    return h


def _hamming(a, b):
    return bin(a ^ b).count("1")


def _bytes_to_mb(n):
    return round(n / (1024 * 1024), 2)


class DatasetCollector:
    """AI 样本采集器"""

    def __init__(self, settings=None):
        self._settings = settings or {}
        self._cooldown_until = 0.0
        self._recent_hashes = []  # 最近样本的 pHash，用于去重
        self._recent_max = 100
        self._lock = threading.Lock()
        self._pending_dir = self.base_dir() / "pending"

    # ---------- 目录 ----------
    def base_dir(self):
        p = self._settings.get("dataset_path") or ""
        if p:
            return Path(p)
        return DEFAULT_PATH

    def dataset_dir(self):
        return self.base_dir() / "dataset"

    def gameplay_dir(self):
        return self.base_dir() / "gameplay"

    def non_gameplay_dir(self):
        return self.base_dir() / "non_gameplay"

    def stats_file(self):
        return self.base_dir() / "dataset_stats.json"

    def ensure_dirs(self):
        for d in [self.gameplay_dir(), self.non_gameplay_dir(), self._pending_dir]:
            try:
                d.mkdir(parents=True, exist_ok=True)
            except Exception:
                return False
        return True

    # ---------- 统计 ----------
    def stats(self):
        g = self._count_dir(self.gameplay_dir())
        n = self._count_dir(self.non_gameplay_dir())
        size = self._dir_size(self.base_dir())
        return {
            "gameplay": g,
            "non_gameplay": n,
            "total": g + n,
            "size_mb": _bytes_to_mb(size),
            "max_mb": MAX_SIZE_MB,
        }

    @staticmethod
    def _count_dir(d):
        try:
            return len([f for f in d.glob("*.jpg") if f.is_file()])
        except Exception:
            return 0

    @staticmethod
    def _dir_size(d):
        try:
            return sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
        except Exception:
            return 0

    # ---------- 采集 ----------
    def _get_frame(self):
        """从主程序取当前帧（在 detector 里由 _apply_event 传入，这里是兜底）"""
        return None

    def capture_gameplay(self, frame, item=""):
        """拾取识别成功后，后台采集 GAMEPLAY 样本"""
        if not self._settings.get("dataset_enabled", False):
            return False
        if frame is None:
            return False
        now = time.time()
        if now < self._cooldown_until:
            return False
        self._cooldown_until = now + COOLDOWN_SECONDS
        threading.Thread(
            target=self._save_sample, args=(frame, "gameplay", item), daemon=True,
        ).start()
        return True

    def capture_manual(self, frame, label):
        """手动采集（GAMEPLAY 或 NON_GAMEPLAY）"""
        if frame is None:
            return False
        if label not in ("gameplay", "non_gameplay"):
            return False
        threading.Thread(
            target=self._save_sample, args=(frame, label, "manual"), daemon=True,
        ).start()
        return True

    def _save_sample(self, frame, label, trigger):
        """后台保存一张样本：缩放→压缩→去重→写盘→统计/容量清理"""
        try:
            if not self.ensure_dirs():
                return
            # 缩放 + 保持 16:9（384×216）
            resized = cv2.resize(frame, (SAVE_W, SAVE_H), interpolation=cv2.INTER_AREA)
            # 去重
            h = _phash(resized)
            with self._lock:
                for ph in self._recent_hashes:
                    if _hamming(h, ph) <= PHASH_DIFF_THRESHOLD:
                        return  # 高度相似，丢弃
                self._recent_hashes.append(h)
                if len(self._recent_hashes) > self._recent_max:
                    self._recent_hashes = self._recent_hashes[-self._recent_max:]
            # 压缩
            ok, buf = cv2.imencode(".jpg", resized, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
            if not ok:
                return
            d = self.gameplay_dir() if label == "gameplay" else self.non_gameplay_dir()
            filename = f"{int(time.time()*1000)}_{label}.jpg"
            filepath = d / filename
            filepath.write_bytes(buf.tobytes())
            # 元数据（不含隐私信息）
            meta = {
                "filename": filename,
                "label": label,
                "trigger": trigger,
                "source_resolution": f"{frame.shape[1]}x{frame.shape[0]}",
                "saved_resolution": f"{SAVE_W}x{SAVE_H}",
            }
            try:
                (d / (filename + ".json")).write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass
            self._enforce_limit()
        except Exception:
            pass

    def _enforce_limit(self):
        """容量控制：接近上限清理，绝不无限增长"""
        size = self._dir_size(self.base_dir())
        if size <= MAX_SIZE_MB * 1024 * 1024:
            return
        # 超过上限：删除最旧样本，直到低于 CLEAN_AT
        target = CLEAN_AT_MB * 1024 * 1024
        files = sorted(
            [f for f in self.base_dir().rglob("*.jpg") if f.is_file()],
            key=lambda f: f.stat().st_mtime,
        )
        for f in files:
            if self._dir_size(self.base_dir()) <= target:
                break
            try:
                f.unlink(missing_ok=True)
                f.with_suffix(".json").unlink(missing_ok=True)
            except Exception:
                pass

    # ---------- 清空 ----------
    def clear_all(self):
        """清空所有样本（只删数据集目录内容）"""
        try:
            for f in self.base_dir().rglob("*"):
                if f.is_file():
                    f.unlink(missing_ok=True)
            return True
        except Exception:
            return False
