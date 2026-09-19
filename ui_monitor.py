# -*- coding: utf-8 -*-
"""主循环 + 监测控制 + 界面刷新。

主循环（_tick_loop）每 200 毫秒跑一次：把检测结果搬进界面、处理托盘动作、
刷新数字、检查是否换日。真正费时的识别跑在后台线程（_detect_loop），
只把结果丢进队列，由主循环取走 —— 这样界面不会卡住。
"""
import queue
import time
import threading
from tkinter import messagebox

import config_manager
import region_selector
import sessions
from detector import Detector
from stats import DailyStats
from ui_base import CARD_INNER, ACCENT, TEXT, DIM, GOOD, BAD, FONT, fmt_time
from overlay_bar import StatBar


class MonitorMixin:
    def _tick_loop(self):
        try:
            # 1. 取检测线程的消息（识别在后台线程跑，这里只收结果，界面不卡）
            try:
                while True:
                    kind, payload = self._detect_queue.get_nowait()
                    if kind == "event":
                        ts, desc = payload
                        self.last_event_label.configure(
                            text=f"🕐 最后识别：{desc}  ({time.strftime('%H:%M:%S', time.localtime(ts))})"
                        )
                    elif kind == "error":
                        self.stop_monitor()
                        self._set_status("监测出错已停止", BAD)
            except queue.Empty:
                pass

            # 2. 托盘动作
            for action in self.tray.poll():
                if action == "show":
                    self.show_main()
                elif action == "start":
                    if not self.monitoring:
                        self.start_monitor()
                elif action == "stop":
                    if self.monitoring:
                        self.stop_monitor()
                elif action == "open_data":
                    self._open_data_dir()
                elif action == "exit":
                    self.on_exit()

            # 3. 刷新界面（内部只在数据变化时重建列表）
            self._refresh_ui()

            # 4. 开发者选项：把后台算好的样本统计显示出来（不阻塞）
            self._apply_dev_stats()

            # 5. 跨过「换日时间」就自动换日（挂过零点也不会一直算同一天）
            try:
                if self.stats.check_day():
                    self._prev_list_sig = None
                    self._refresh_ui()
                    if "records" in getattr(self, "_pages", {}):
                        self._rebuild_records()
            except Exception:
                pass
        except Exception:
            pass
        # 界面刷新频率固定 200ms（检测频率由后台线程控制）
        self.after(200, self._tick_loop)

    def on_start_stop(self):
        if self.monitoring:
            self.stop_monitor()
        else:
            self.start_monitor()

    def _prewarm_ocr(self):
        """主线程预热 OCR 模型（避免后台线程首次加载 onnxruntime 的潜在问题）"""
        try:
            from ocr_engine import OcrEngine
            ocr = OcrEngine()
            ocr._ensure()
            import numpy as np
            ocr.recognize_line(np.zeros((40, 400, 3), dtype=np.uint8))
        except Exception:
            pass

    def start_monitor(self):
        # 预热 OCR 模型（主线程加载，1~3秒；避免后台线程首次加载闪退）
        self._set_status("正在加载识别模型…", DIM)
        self.update_idletasks()
        self._prewarm_ocr()
        # 优先用【自动扫全屏游戏窗口】：材料/圣遗物拾取提示出现在哪都能识别，
        # 摩拉位置也不用手动指定。找不到游戏窗口时才退回手动框选区域。
        from capture import find_game_window
        win = find_game_window()
        region = None
        mode_text = "正在监测（自动识别游戏窗口）"
        if win is None:
            # 没有游戏窗口 → 用之前框选的手动区域（若有）
            region = self.settings.get("region")
            if not region:
                messagebox.showinfo("提示", "没有找到原神游戏窗口。\n\n请先打开游戏（用无边框窗口模式），再点开始监测。")
                return
            mode_text = "正在监测"
        # 启动后台检测线程（OCR 很慢，必须在后台跑，否则界面卡死）
        self._detect_stop = threading.Event()
        self._detect_queue = queue.Queue()
        self._detect_err_streak = 0
        self._detect_thread = threading.Thread(
            target=self._detect_loop, args=(region,), daemon=True
        )
        self._detect_thread.start()
        self.monitoring = True
        self._monitor_start = time.monotonic()
        # 收益记录：记下开始时的数据快照，停止时算差值写一条记录
        self._sess_start_ts = time.time()
        self._sess_snapshot = (
            self.stats.mora,
            self.stats.artifact,
            dict(self.stats.materials),
            dict(self.stats.normal_materials),
        )
        self._set_status(mode_text, GOOD)
        self._set_start_ui(True)

    def _detect_loop(self, region):
        """后台检测线程：识别（含慢速OCR）全部在这里跑，主线程只管界面"""
        stop_ev = self._detect_stop  # 局部引用，避免主线程置 None 后竞态
        try:
            det = Detector(region, ICONS_DIR, self.settings, stats=self.stats)
        except Exception as e:
            try:
                self._detect_queue.put(("error", str(e)))
            except Exception:
                pass
            return
        self.detector = det
        try:
            last_ts = None
            while stop_ev is not None and not stop_ev.is_set():
                try:
                    det.tick()
                    self._detect_err_streak = 0
                except Exception:
                    # 连续出错才上报停止（偶尔一次不影响）
                    self._detect_err_streak += 1
                    if self._detect_err_streak > 20:
                        try:
                            self._detect_queue.put(("error", "连续识别失败"))
                        except Exception:
                            pass
                        break
                # 识别到新事件 → 报给主线程显示
                ev = det.last_event
                if ev is not None and ev[0] != last_ts:
                    last_ts = ev[0]
                    try:
                        self._detect_queue.put(("event", ev))
                    except Exception:
                        pass
                interval = max(0.02, int(self.settings.get("tick_interval", 50)) / 1000.0)
                stop_ev.wait(interval)
        finally:
            try:
                det.close()
            except Exception:
                pass
            self.detector = None

    def stop_monitor(self):
        if self.monitoring and self._monitor_start:
            self.stats.running_seconds += int(time.monotonic() - self._monitor_start)
            self.stats.save()
        self._record_session()   # 写入「收益记录」
        self.monitoring = False
        self._monitor_start = None
        # 停止后台检测线程（daemon，不 join 避免卡界面；detector 在线程内已 close）
        if self._detect_stop is not None:
            try:
                self._detect_stop.set()
            except Exception:
                pass
        self._detect_stop = None
        self._detect_thread = None
        self._set_status("已暂停", BAD)
        self._set_start_ui(False)

    def _record_session(self):
        """把这次监测的收益差值写进「收益记录」"""
        try:
            snap = getattr(self, "_sess_snapshot", None)
            start_ts = getattr(self, "_sess_start_ts", None)
            if snap is None or start_ts is None:
                return
            self._sess_snapshot = None
            self._sess_start_ts = None
            s_mora, s_art, s_mat, s_norm = snap
            # 当前材料（怪物 + 普通合并）
            cur = dict(self.stats.materials)
            for k, v in self.stats.normal_materials.items():
                cur[k] = cur.get(k, 0) + v
            old = dict(s_mat)
            for k, v in s_norm.items():
                old[k] = old.get(k, 0) + v
            gained = {}
            for k, v in cur.items():
                d = int(v) - int(old.get(k, 0))
                if d > 0:
                    gained[k] = d
            now = time.time()
            rec = sessions.make_record(
                start_ts, now, now - start_ts,
                self.stats.mora - s_mora,
                self.stats.artifact - s_art,
                gained,
            )
            sessions.add_session(rec)
            try:
                self._rebuild_records()
            except Exception:
                pass
        except Exception:
            pass

    def on_reselect(self):
        """重新框选识别区域（不隐藏主窗口，遮罩本身在最顶层）"""
        was_monitoring = self.monitoring
        if was_monitoring:
            self.stop_monitor()
        try:
            region = region_selector.select_region(self)
        except Exception as e:
            messagebox.showerror(
                "框选失败",
                f"框选出现错误：{e}\n\n请再试一次。\n提示：如果看不到框选界面，可能是游戏全屏独占，"
                "请按 Esc 取消，把游戏改成无边框窗口模式。",
            )
            return
        if region:
            self.settings["region"] = region
            config_manager.save_settings(self.settings)
            if self.detector:
                self.detector.region = region  # 检测器直接用新区域
            messagebox.showinfo("成功", "识别区域已更新")
        self._refresh_region_state()

    def _set_start_ui(self, running):
        """开始/停止监测时，同步更新启动页那张卡片（标题 + 按钮）"""
        try:
            self.start_card_title.configure(text="停止监测" if running else "开始监测")
            self.start_card_btn.configure(text="停止" if running else "开始")
        except Exception:
            pass

    def _refresh_region_state(self):
        r = self.settings.get("region")
        if not r:
            # 自动模式：不用框选，程序自动找游戏窗口
            self._set_status("未框选（自动检测游戏窗口）", DIM)
            self._set_start_ui(False)
            try:
                self.launch_region_label.configure(text="自动检测游戏窗口（也可「重新框选」手动指定）")
            except Exception:
                pass
        else:
            self._set_start_ui(False)
            try:
                self.launch_region_label.configure(text=f"({r['x']}, {r['y']})  {r['w']}×{r['h']}")
            except Exception:
                pass

    def _set_status(self, text, color=None):
        color = color or TEXT
        dot = {"#4A90D9": "●", "#9E9E9E": "●", "#F2F2F2": "●"}.get(color, "●")
        self.status_label.configure(text=f"{dot} {text}", text_color=color)
        try:
            self.launch_status_label.configure(text=f"{dot} {text}", text_color=color)
        except Exception:
            pass

    def _refresh_ui(self):
        # 「今日统计」页还没建（懒加载）时跳过，建好后 _show_page 会再刷一次
        if "home" not in getattr(self, "_pages", {}):
            return
        try:
            # 只在数值真的变了才 configure（每次 configure 都会触发控件重绘）
            _mora = f"{self.stats.mora:,}"
            if getattr(self, "_ui_mora_txt", None) != _mora:
                self._ui_mora_txt = _mora
                self.mora_label.configure(text=_mora)

            total = self.stats.running_seconds
            if self.monitoring and self._monitor_start:
                total += int(time.monotonic() - self._monitor_start)
            _t = fmt_time(total)
            if getattr(self, "_ui_time_txt", None) != _t:
                self._ui_time_txt = _t
                self.time_label.configure(text=_t)

            _art = f"×{self.stats.artifact}"
            if getattr(self, "_ui_art_txt", None) != _art:
                self._ui_art_txt = _art
                self.artifact_label.configure(text=_art)

            # 素材列表（合并材料，只在数据变化时重建）
            merged = dict(self.stats.materials)
            for k, v in self.stats.normal_materials.items():
                merged[k] = merged.get(k, 0) + v
            sig = (self.stats.mora, self.stats.artifact, tuple(sorted(merged.items())))
            if sig != self._prev_list_sig:
                self._prev_list_sig = sig
                self._rebuild_mat_list(merged)
                self._rebuild_detail_list()
        except Exception:
            pass
