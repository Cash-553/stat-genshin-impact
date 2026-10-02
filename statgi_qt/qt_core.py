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
        self.paused = False      # 暂停（区别于停止：会话还在）
        # 「连续失败计数」搬去 svc_capture.run_detector 了（本来也没人读它）
        self.detector = None
        self._sess_start_ts = None
        self._sess_snapshot = None
        # 跨天结转：「会话开始 → 换日前」那段已经赚到的增量先寄存在这里，
        # 换日之后 `_sess_snapshot` 会被重设成 0，结束时两段相加才算得完整。
        # 结构固定成 {"mora": int, "artifact": int, "materials": {名字: 数量}}
        self._sess_carry = None

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
        #
        #    ⚠ 换日会把今日计数清零（mora / artifact / materials 全归 0）。
        #      挂机跨天时「本次会话」是横跨两个自然日的，如果不管，
        #      结束时算增量就成了 max(0, 0 - 换日前的 5000) = 0 —— 一整晚白挂。
        #      所以必须**在 check_day() 之前**把今日快照留下来（调用之后
        #      stats.mora 已经是 0，再读就晚了），交给 _carry_session 结转。
        try:
            if bool((self.settings or {}).get("rollover_enabled", True)):
                # 只有真有一段会话在跑时才需要留快照（否则白拷贝几份 dict）
                live = bool(self.monitoring or getattr(self, "paused", False))
                pre = ((self.stats.mora, self.stats.artifact,
                        dict(self.stats.materials),
                        dict(self.stats.normal_materials)) if live else None)
                if self.stats.check_day():
                    self._last = None
                    if live and pre is not None:
                        self._carry_session(pre)
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
        elif getattr(self, "paused", False):
            # ⚠ 暂停中按热键＝**继续**，不能走 start()。
            #   start() 会把 _sess_start_ts / _sess_snapshot 重置成新的一段，
            #   等于把暂停前挂的那段收益记录丢掉。
            self.resume()
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
        ok, mode_text = self._spawn_detect(on_error)
        if not ok:
            return

        self.monitoring = True
        self.paused = False
        self._monitor_start = time.monotonic()
        self._sess_start_ts = time.time()
        self._sess_snapshot = (
            self.stats.mora, self.stats.artifact,
            dict(self.stats.materials), dict(self.stats.normal_materials))
        self._sess_carry = self._new_carry()   # 新的一段挂机 = 从零开始结转
        self.status_changed.emit(mode_text, GOOD)
        self.force_refresh()

    def _spawn_detect(self, on_error=None):
        """找游戏窗口 + 起后台识别线程。返回 (成功?, 状态文字)。

        start() 和 resume() 都用它 —— 暂停后继续时窗口可能已经换了，
        所以**每次都要重新找**，不能缓存。
        """
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
                    on_error("没有找到原神游戏窗口。\n\n请先打开游戏"
                             "（用无边框窗口模式），再点开始监测。")
                self.status_changed.emit("未开始", DIM)
                return False, mode_text
            mode_text = "正在监测"

        self._detect_stop = threading.Event()
        self._detect_queue = queue.Queue()
        self._detect_thread = threading.Thread(
            target=self._detect_loop, args=(region,), daemon=True)
        self._detect_thread.start()
        return True, mode_text

    def pause(self):
        """暂停：停掉识别，但**本次会话留着**。

        跟 stop() 的区别就在这几行：
            · **不调 `_record_session()`** —— 不写收益记录
            · **不发 `session_ended`** —— 不弹「本次小结」
            · **不动 `_sess_start_ts` / `_sess_snapshot`** —— 还是同一段
        继续（resume）时接着这一段跑，数据不清零。

        计时照常结算：把已跑的时间累加进 `stats.running_seconds`，
        继续时从当前时刻重新起算 —— 所以「监测时间」只统计真正在识别的时长。
        """
        if not self.monitoring:
            return
        if self._monitor_start:
            self.stats.running_seconds += int(time.monotonic()
                                             - self._monitor_start)
            try:
                self.stats.save()
            except Exception:
                pass
            self._monitor_start = None
        self.monitoring = False
        self.paused = True
        if self._detect_stop is not None:
            try:
                self._detect_stop.set()
            except Exception:
                pass
        self._detect_stop = None
        self._detect_thread = None
        self.status_changed.emit("已暂停", DIM)
        self.force_refresh()

    def resume(self, on_error=None):
        """继续：接着暂停前那一段会话跑，收益记录不重开。"""
        if not self.paused:
            return
        ok, mode_text = self._spawn_detect(on_error)
        if not ok:
            # 起不来（窗口没了）→ 退出暂停态，界面回到「未开始」，
            # 但**会话状态仍然留着**，下次点开始还是接着这一段
            self.paused = False
            self.force_refresh()
            return
        self.paused = False
        self.monitoring = True
        self._monitor_start = time.monotonic()
        self.status_changed.emit(mode_text, GOOD)
        self.force_refresh()

    def _detect_loop(self, region):
        """后台线程：识别（含慢速 OCR）全在这里跑，主线程只管界面

        ⚠ 分工：**线程 / 队列 / 谁造谁清 Detector 留在本类**，
          那一轮循环本身在 `svc_capture.run_detector`。
          搬走的只是「怎么跟识别器说话」，线程那套一个字没动。

        **卡死自动重启**（2026-09-29 加）：
            `run_detector` 返回 "failed" = 识别连续出错超过 3 秒，判定卡死。
            这时**重建一个 Detector** 再跑，而不是直接停下等人来点 ——
            重建会重新申请截图资源、重新找游戏窗口、重建 OCR 会话，
            能兜住「资源耗尽 / 句柄失效」这一大类问题。

            最多重启 3 次；还不行才真的停下并提示用户。
        """
        stop_ev = self._detect_stop
        restarts = 0
        while True:
            try:
                det = svc_capture.make_detector(region, self.settings,
                                                self.stats)
            except Exception as e:
                try:
                    self._detect_queue.put(("error", str(e)))
                except Exception:
                    pass
                return
            self.detector = det
            try:
                why = svc_capture.run_detector(det, stop_ev, self.settings,
                                               self._detect_queue)
            finally:
                # 只有"当前这个"才清空 —— 万一用户停完马上又开了一个，
                # 旧线程收尾时不能把新 detector 抹掉
                if self.detector is det:
                    self.detector = None

            # 用户点了停止，或者不是「卡死」→ 正常收工
            if stop_ev.is_set() or why != "failed":
                return

            restarts += 1
            if restarts > svc_capture.MAX_RESTARTS:
                try:
                    self._detect_queue.put(
                        ("error",
                         f"识别反复失败，已自动重试 "
                         f"{svc_capture.MAX_RESTARTS} 次仍未恢复"))
                except Exception:
                    pass
                return

            try:
                self._detect_queue.put(
                    ("status",
                     f"识别出错，正在自动重试（第 {restarts}/"
                     f"{svc_capture.MAX_RESTARTS} 次）…"))
            except Exception:
                pass
            # 缓一下再重建；用户中途点停止就立刻退出
            if stop_ev.wait(svc_capture.RESTART_WAIT):
                return

    def reset_monitor_start(self):
        """清空监测时间后，让计时从 0 重新累计"""
        self._monitor_start = time.monotonic() if self.monitoring else None
        self.force_refresh()

    def stop(self):
        # ⚠ 暂停中也要能停：暂停时 monitoring 已经是 False，
        #   如果这里直接 return，关程序时 _record_session() 就不会跑，
        #   这一整段挂机的收益记录就丢了。
        if not self.monitoring and not getattr(self, "paused", False):
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
        self.paused = False          # 停止＝真的结束这一段（跟暂停不同）
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
        self.status_changed.emit("已停止", BAD)
        self.force_refresh()

    # ================= 跨天结转 =================

    @staticmethod
    def _new_carry():
        """一份空的结转累加器"""
        return {"mora": 0, "artifact": 0, "materials": {}}

    def _carry_session(self, pre):
        """换日那一刻：把「会话开始 → 换日前」的增量收进 `_sess_carry`。

        **必须在 `stats.check_day()` 之后、且用换日前的快照 `pre` 来算** ——
        换日已经把今日计数清零了，拿现在的 stats 算出来永远是 0。

        算完把 `_sess_snapshot` 重设成 0，这样结束时的「换日后增量」不会
        把换日前那段重复算一遍（两段相加才是完整的一次挂机）。

        ⚠ `_sess_start_ts` **不要重置** —— 这一段挂机还没结束，
          收益记录里的时长要照旧从会话开始算。
        """
        if not self._sess_snapshot:
            return
        m0, a0, mat0, norm0 = self._sess_snapshot
        carry = self._sess_carry or self._new_carry()
        carry["mora"] += max(0, int(pre[0]) - int(m0))
        carry["artifact"] += max(0, int(pre[1]) - int(a0))
        merged = {}
        for k, v in list(pre[2].items()) + list(pre[3].items()):
            merged[k] = merged.get(k, 0) + v
        for k, v in list(mat0.items()) + list(norm0.items()):
            merged[k] = merged.get(k, 0) - v
        mats = carry["materials"]
        for k, v in merged.items():
            if v > 0:
                mats[k] = mats.get(k, 0) + v
        self._sess_carry = carry
        # 换日后的新基线 = 清零后的 0（时长基线不在这里 —— 它走墙上时间）
        self._sess_snapshot = (0, 0, {}, {})

    def _record_session(self):
        """把这次监测的收益差值写进「收益记录」

        返回刚写进去的那条记录 dict（没写就返回 None）——
        窗口拿它弹「本次小结」（`session_ended` 信号）。

        ⚠ 跨天挂机：这次会话可能横跨了换日（`stats` 被清零过），
          所以收益 = **`_sess_carry`（换日前那段）+ 换日后的增量**，
          少加一段记录里就会缺一整晚（见 `_carry_session`）。
          时间轴不受影响 —— `_sess_start_ts` 跨天没动过，时长照旧一整段。

        ⚠ **写进文件里了才算数**（2026-09-30 修）：
          以前不管写没写成，`finally` 都把基线/起点/结转擦干净 ——
          而落盘那一步（`sessions._save`）是**出错也不吭声**的，
          于是"没存进去"和"存进去了"在调用方看来一模一样：
          界面照样弹小结、其实 `sessions.json` 里什么都没有，
          而且现场已经清空、**再也补不回来**，报错日志里也没痕迹。
          现在：先看记录条数有没有真的涨、再决定清不清现场；
          没写成就**留着现场**（下次停的时候还能再试一次），并记进报错日志。
        """
        rec = None
        recorded = False
        try:
            if not self._sess_snapshot:
                recorded = True         # 压根没有会话，没什么可清的
                return None
            if not self._sess_start_ts:
                recorded = True
                return None
            m0, a0, mat0, norm0 = self._sess_snapshot
            carry = self._sess_carry or self._new_carry()
            m1, a1 = self.stats.mora, self.stats.artifact
            mat1 = dict(self.stats.materials)
            norm1 = dict(self.stats.normal_materials)
            delta = dict(carry["materials"])
            for k, v in list(mat1.items()) + list(norm1.items()):
                delta[k] = delta.get(k, 0) + v
            for k, v in list(mat0.items()) + list(norm0.items()):
                delta[k] = delta.get(k, 0) - v
            delta = {k: v for k, v in delta.items() if v > 0}
            gained_mora = carry["mora"] + max(0, m1 - m0)
            gained_artifact = carry["artifact"] + max(0, a1 - a0)
            seconds = int(time.time() - self._sess_start_ts)
            if (seconds < 5 and not delta and not gained_mora
                    and not gained_artifact):
                # 什么都没干：不记，而且**现场也要清掉** ——
                # 留着的话，停止之后新赚的那点收益会被算进这段已经结束的会话。
                self._sess_snapshot = None
                self._sess_start_ts = None
                self._sess_carry = None
                recorded = True
                return None
            rec = svc_records.make_record(
                self._sess_start_ts, time.time(), seconds,
                gained_mora, gained_artifact, delta)
            before = len(svc_records.load_sessions())
            svc_records.add_session(rec)
            recorded = len(svc_records.load_sessions()) > before
            if not recorded:
                rec = None              # 以为写进去了，其实文件没变
                try:
                    # 落盘那一步是"出错也不吭声"的（sessions._save），
                    # 这里必须自己喊一声，否则事后完全没有线索。
                    import errlog
                    errlog.log_msg(
                        "写收益记录",
                        f"收益记录没能写进文件（读了 {before} 条、写完还是 "
                        f"{before} 条）—— 现场已保留，下次停止时会再试一次")
                except Exception:
                    pass
        except Exception:
            rec = None
            recorded = False
            try:
                import errlog
                errlog.log_exc("写收益记录")
            except Exception:
                pass
        if recorded:
            # 只有真存进文件了才擦现场 —— 失败就留着，别把一整晚丢掉
            self._sess_snapshot = None
            self._sess_start_ts = None
            self._sess_carry = None
        return rec

    @staticmethod
    def _prewarm_ocr():
        """预热 OCR 模型 —— 具体怎么做在 `svc_capture.prewarm_ocr`。

        ⚠ 这个方法留着不删：`_morph\\api_snapshot.py` 会把类的私有方法也
          算进"对外表面"，删了它会报「方法丢了」。
        """
        svc_capture.prewarm_ocr()
