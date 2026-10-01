# -*- coding: utf-8 -*-
"""StatGI Qt 版 · 数据与监测核心

一个 AppState 对象，界面全部从它拿数据。

刷新机制（重点，按"不重绘整个窗口"的原则设计）：
  · 全程序**只有一个定时器**（200ms），就是这里的 _tick
  · _tick 只做三件事：排空识别队列 / 检查换日 / 比较数据有没有变
  · **数据没变就一个信号都不发** —— 界面完全不动
  · 数据变了只发 stats_changed，页面自己去比"哪个数字不一样"，
    只改那一个标签；列表按名字增量更新，不重建控件
"""
import queue
import threading
import time

from PySide6.QtCore import QObject, QTimer, Signal

import config_manager
import paths
import svc_capture
import svc_records
from stats import DailyStats

GOOD = "#6CCB5F"
BAD = "#E06C5A"
DIM = "#9A9A9A"

ICONS_DIR = paths.icons_dir()


class AppState(QObject):
    """程序的状态：统计 + 监测控制 + 唯一的那个刷新定时器"""

    stats_changed = Signal()               # 数字 / 材料变了
    status_changed = Signal(str, str)      # 状态文字, 颜色
    event_happened = Signal(str, float)    # 最近一次识别（描述, 时间戳）
    session_ended = Signal(object)         # 本次监测结束（参数=刚写进记录的那条 dict）

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        try:
            self.stats = DailyStats(rollover_hour=int(settings.get("rollover_hour", 0) or 0))
        except Exception:
            self.stats = DailyStats()

        # ---- 监测状态 ----
        self.monitoring = False
        self._monitor_start = None
        self._detect_thread = None
        self._detect_stop = None
        self._detect_queue = None
        # 「连续失败计数」搬去 svc_capture.run_detector 了（本来也没人读它）
        self.detector = None
        self._sess_start_ts = None
        self._sess_snapshot = None

        # ---- 上一轮的数据快照：用来判断"到底变了没有" ----
        self._last = None

        # 全程序唯一的刷新定时器
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(200)

    # ================= 数据 =================
    def snapshot(self):
        merged = dict(self.stats.materials)
        for k, v in self.stats.normal_materials.items():
            merged[k] = merged.get(k, 0) + v
        total = self.stats.running_seconds
        if self.monitoring and self._monitor_start:
            total += int(time.monotonic() - self._monitor_start)
        return {
            "mora": self.stats.mora,
            "artifact": self.stats.artifact,
            "seconds": total,
            "materials": merged,
        }

    def _tick(self):
        # 1) 排空识别线程的消息（识别在后台线程跑，这里只收结果）
        if self._detect_queue is not None:
            try:
                while True:
                    kind, payload = self._detect_queue.get_nowait()
                    if kind == "event":
                        ts, desc = payload
                        self.event_happened.emit(desc, ts)
                    elif kind == "error":
                        self.stop()
                        self.status_changed.emit("监测出错已停止", BAD)
                    elif kind == "status":
                        # 只更新状态文字，**不停止** ——
                        # 比如「找不到游戏窗口」（游戏关了/重启了），
                        # 窗口回来之后下一轮自己就恢复了。
                        self.status_changed.emit(str(payload), BAD)
            except queue.Empty:
                pass
            except Exception:
                pass

        # 2) 跨过换日时间就自动换日
        #    设置里可以把「换日刷新数据」关掉 —— 关了就完全不换日，
        #    数据一直累着，直到手动清空。
        try:
            if bool((self.settings or {}).get("rollover_enabled", True)):
                if self.stats.check_day():
                    self._last = None
        except Exception:
            pass

        # 3) 数据真的变了才发信号 —— 没变的话界面一个像素都不动
        snap = self.snapshot()
        key = (snap["mora"], snap["artifact"], snap["seconds"], tuple(sorted(snap["materials"].items())))
        if key != self._last:
            self._last = key
            self.stats_changed.emit()

    def force_refresh(self):
        """要强制界面按最新数据刷一次（比如刚切到某页）"""
        self._last = None
        self._tick()

    # ================= 设置 =================
    def set_setting(self, path, value):
        """改一个设置项并**立即存盘**（没有保存按钮）

        path 支持点号路径，比如 "stat_bar.opacity"。
        """
        try:
            parts = path.split(".")
            d = self.settings
            for p in parts[:-1]:
                if not isinstance(d.get(p), dict):
                    d[p] = {}
                d = d[p]
            d[parts[-1]] = value
            config_manager.save_settings(self.settings)
        except Exception:
            pass

    def get_setting(self, path, default=None):
        d = self.settings
        for p in path.split("."):
            if not isinstance(d, dict) or p not in d:
                return default
            d = d[p]
        return d

    def apply_live_settings(self):
        """把改了设置立刻推给**正在运行**的识别线程。

        ⚠ 具体推哪几个值、为什么是那几个 —— 见 `svc_capture.apply_live_settings`。
          那是"识别管线怎么说话"的知识，搬去 service 了。
        """
        svc_capture.apply_live_settings(getattr(self, "detector", None),
                                       self.settings)

    # ================= 监测 =================
    def toggle(self):
        if self.monitoring:
            self.stop()
        else:
            self.start()

    def start(self, on_error=None):
        # 已经在监测就别再开一个线程 —— 否则会有两个识别线程一起跑，
        # 而且旧的停不掉（用户点「停止」其实是在又开一个）
        if self.monitoring:
            return
        # 预热 OCR 模型：主线程加载，避免后台线程首次加载 onnxruntime 出问题
        self.status_changed.emit("正在加载识别模型…", DIM)
        self._prewarm_ocr()

        # 优先自动找游戏窗口；找不到才退回手动框选的区域
        region = None
        mode_text = "正在监测（自动识别游戏窗口）"
        try:
            win = svc_capture.find_game_window()
        except Exception:
            win = None
        if win is None:
            region = self.settings.get("region")
            if not region:
                if on_error:
                    on_error("没有找到原神游戏窗口。\n\n请先打开游戏（用无边框窗口模式），再点开始监测。")
                self.status_changed.emit("未开始", DIM)
                return
            mode_text = "正在监测"

        # 启动后台检测线程
        self._detect_stop = threading.Event()
        self._detect_queue = queue.Queue()
        self._detect_thread = threading.Thread(
            target=self._detect_loop, args=(region,), daemon=True)
        self._detect_thread.start()

        self.monitoring = True
        self._monitor_start = time.monotonic()
        self._sess_start_ts = time.time()
        self._sess_snapshot = (
            self.stats.mora, self.stats.artifact,
            dict(self.stats.materials), dict(self.stats.normal_materials))
        self.status_changed.emit(mode_text, GOOD)
        self.force_refresh()

    def _detect_loop(self, region):
        """后台线程：识别（含慢速 OCR）全在这里跑，主线程只管界面

        ⚠ 分工：**线程 / 队列 / 谁造谁清 Detector 留在本类**，
          那一轮循环本身在 `svc_capture.run_detector`。
          搬走的只是「怎么跟识别器说话」，线程那套一个字没动。
        """
        stop_ev = self._detect_stop
        try:
            det = svc_capture.make_detector(region, self.settings, self.stats)
        except Exception as e:
            try:
                self._detect_queue.put(("error", str(e)))
            except Exception:
                pass
            return
        self.detector = det
        try:
            svc_capture.run_detector(det, stop_ev, self.settings,
                                     self._detect_queue)
        finally:
            # 只有"当前这个"才清空 —— 万一用户停完马上又开了一个，
            # 旧线程收尾时不能把新 detector 抹掉
            if self.detector is det:
                self.detector = None

    def reset_monitor_start(self):
        """清空监测时间后，让计时从 0 重新累计"""
        self._monitor_start = time.monotonic() if self.monitoring else None
        self.force_refresh()

    def stop(self):
        if not self.monitoring:
            return
        if self._monitor_start:
            self.stats.running_seconds += int(time.monotonic() - self._monitor_start)
            try:
                self.stats.save()
            except Exception:
                pass
        # 先把状态标记成"已停止"，界面立刻就有反应；
        # 再通知后台线程退出（它可能正在跑一次 OCR，要等它跑完那一轮）
        self.monitoring = False
        self._monitor_start = None
        rec = self._record_session()
        if rec:
            # 给窗口用：弹「本次小结」。退出程序的那条路不会弹（见 qt_window）。
            try:
                self.session_ended.emit(rec)
            except Exception:
                pass
        if self._detect_stop is not None:
            try:
                self._detect_stop.set()
            except Exception:
                pass
        self._detect_stop = None
        self._detect_thread = None
        self.status_changed.emit("已暂停", BAD)
        self.force_refresh()

    def _record_session(self):
        """把这次监测的收益差值写进「收益记录」

        返回刚写进去的那条记录 dict（没写就返回 None）——
        窗口拿它弹「本次小结」（`session_ended` 信号）。
        """
        rec = None
        try:
            if not self._sess_snapshot:
                return None
            if not self._sess_start_ts:
                return None
            m0, a0, mat0, norm0 = self._sess_snapshot
            m1, a1 = self.stats.mora, self.stats.artifact
            mat1 = dict(self.stats.materials)
            norm1 = dict(self.stats.normal_materials)
            delta = {}
            for k, v in list(mat1.items()) + list(norm1.items()):
                delta[k] = delta.get(k, 0) + v
            for k, v in list(mat0.items()) + list(norm0.items()):
                delta[k] = delta.get(k, 0) - v
            delta = {k: v for k, v in delta.items() if v > 0}
            seconds = int(time.time() - self._sess_start_ts)
            if seconds < 5 and not delta and m1 == m0 and a1 == a0:
                return None         # 什么都没干，不记
            rec = svc_records.make_record(
                self._sess_start_ts, time.time(), seconds,
                max(0, m1 - m0), max(0, a1 - a0), delta)
            svc_records.add_session(rec)
        except Exception:
            rec = None
        finally:
            self._sess_snapshot = None
            self._sess_start_ts = None
        return rec

    @staticmethod
    def _prewarm_ocr():
        """预热 OCR 模型 —— 具体怎么做在 `svc_capture.prewarm_ocr`。

        ⚠ 这个方法留着不删：`_morph\\api_snapshot.py` 会把类的私有方法也
          算进"对外表面"，删了它会报「方法丢了」。
        """
        svc_capture.prewarm_ocr()
