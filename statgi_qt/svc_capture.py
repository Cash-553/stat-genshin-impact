# -*- coding: utf-8 -*-
"""识别管线服务 —— UI 只跟这里打交道，不直接 import capture / detector / ocr_engine。

第 4 步（service 层）4.4。**这是整个第 4 步风险最高的一步** ——
识别线程和 UI 线程在这里交界。

⚠ 所以分工是刻意划开的：

    **留在 `qt_core.AppState`**：线程、队列、停止事件、QTimer、生命周期
    **搬到本模块**：怎么跟识别管线说话（找窗口 / 预热 / 造 Detector /
                   跑那一轮循环 / 把设置推给正在跑的 Detector / 问一个名字是不是圣遗物）

    线程那一套一个字没动 —— 搬过来的只是「管线知识」。

背后挡着四样（原来 UI 各自 import）：

    capture             截图 / 找游戏窗口
    detector            识别器（tick / last_event / close / reload_names）
    ocr_engine          OCR（预热、识别一行）
    dataset_collector    开发页的样本采集

⚠ 契约见根目录 `第4步-service契约.md`。

⚠ 为什么这里的 import 都写在**函数体里**（懒加载）：
   跟原来的写法一致 —— `detector` 会拖进 onnxruntime，启动时不该付这个代价。
"""
import paths

ICONS_DIR = paths.icons_dir()


# ============================================================ 屏幕 / 窗口
def find_game_window():
    """自动找原神游戏窗口。找不到返回 None（调用方要处理这个情况）。"""
    from capture import find_game_window as _find
    return _find()


def grab(region):
    """截一帧，返回 numpy 数组（RGB）。

    `region` 是 {"x","y","w","h"}。自己开关 ScreenCapture ——
    原来 UI 各处都要写一遍 `c = ScreenCapture(); ...; c.close()`，
    漏掉 close 就会漏句柄。
    """
    from capture import ScreenCapture
    cap = ScreenCapture()
    try:
        return cap.grab(region)
    finally:
        cap.close()


# ============================================================ OCR
def prewarm_ocr():
    """预热 OCR 模型（**主线程**调，避免后台线程首次加载 onnxruntime 出问题）。

    空跑一次推理，把内存池和图形优化都建好 —— 不然用户点「开始监测」之后
    第一次识别会明显卡一下。失败就算了，识别时会自己再加载一遍。
    """
    try:
        import numpy as np
        from ocr_engine import OcrEngine
        ocr = OcrEngine()
        ocr._ensure()
        ocr.recognize_line(np.zeros((40, 400, 3), dtype=np.uint8))
    except Exception:
        pass


def recognize(frame):
    """识别一帧里的所有文字行，返回 [(文本, 置信度), …]。"""
    from ocr_engine import OcrEngine
    return OcrEngine().recognize(frame)


# ============================================================ 识别器
def make_detector(region, settings, stats):
    """造一个 Detector（**必须在要跑它的那个线程里造**）。

    原样搬自 AppState._detect_loop。构造可能抛异常（模型加载失败之类），
    调用方负责 catch 并上报 —— 这里不吞异常。
    """
    from detector import Detector
    return Detector(region, ICONS_DIR, settings, stats=stats)


def tick_interval(settings):
    """两轮识别之间睡多久（秒）。下限 20ms，读不到设置就 50ms。"""
    try:
        return max(0.02, int(settings.get("tick_interval", 50)) / 1000.0)
    except Exception:
        return 0.05


def run_detector(det, stop_ev, settings, out_queue):
    """跑识别循环，直到 `stop_ev` 被设。**这是后台线程的主体。**

    原样搬自 AppState._detect_loop 的循环体，语义一条没改：

      · `det.tick()` 抛异常就记一次；**连续 20 次**往队列里报致命错然后退出
      · tick 抛异常也照样读 `det.last_event`（原代码就是这样的）
      · 读到的 `last_event` **时间戳变了才上报** —— 同一件事不重复报
      · 每轮末尾 `stop_ev.wait(间隔)`
      · **无论如何最后 `det.close()`**

    `out_queue` 里塞两种消息（塞不进去就忽略，跟原来一样）：
        ("event", (时间戳, 描述))   ("error", "连续识别失败")
    """
    last_ts = None
    err_streak = 0
    # ⚠ `close()` 必须在 finally 里 —— 原代码就是 try/finally。
    #   写成"循环后面的普通语句"的话，中途抛异常（比如 det.last_event 炸了）
    #   就会跳过 close，句柄泄漏。线程交界处别省这一层。
    try:
        while stop_ev is not None and not stop_ev.is_set():
            try:
                det.tick()
                err_streak = 0
            except Exception as _e:
                err_streak += 1
                # 前几次把**真实异常**记下来。
                # 原来这里只有一句 `except Exception:` —— 异常内容被彻底吞掉，
                # 事后只知道「连错了 20 次」，不知道错的是什么，只能靠猜。
                # 写进 data/日志/报错/报错_<日期>.log（同一条 30 秒去重）。
                if err_streak <= 3:
                    try:
                        import errlog
                        errlog.log_exc("识别循环")
                    except Exception:
                        pass
                if err_streak > 20:
                    try:
                        import errlog
                        errlog.log_msg(
                            "识别循环",
                            f"连续出错 {err_streak} 次，已停止监测"
                            f"（最后一次：{type(_e).__name__}: {_e}）")
                    except Exception:
                        pass
                    try:
                        out_queue.put(("error", "连续识别失败"))
                    except Exception:
                        pass
                    break

            ev = det.last_event
            if ev is not None and ev[0] != last_ts:
                last_ts = ev[0]
                try:
                    out_queue.put(("event", ev))
                except Exception:
                    pass

            # 长时间抓不到画面 —— 大概率是游戏窗口关了 / 重启了 / 最小化了。
            # 原来这种情况**完全静默**：界面上还写着「正在监测」，
            # 其实一个都不识别，用户只能感觉「突然不识别了」。
            # 这里每累计 60 次（约 3 秒）报一条状态，让界面能提示出来。
            miss = getattr(det, "_grab_miss", 0)
            if miss and miss % 60 == 1:
                try:
                    out_queue.put(("status", "找不到游戏窗口，已暂停识别"))
                except Exception:
                    pass

            stop_ev.wait(tick_interval(settings))
    finally:
        try:
            det.close()
        except Exception:
            pass


def apply_live_settings(det, settings):
    """把改了设置立刻推给**正在运行**的 Detector。

    识别线程是用 settings 这个 dict 构造 Detector 的，而 Detector 在构造时
    把一部分值**复制**成自己的属性 —— 所以光改 settings 它不会变。

    哪些要推（看 detector.py 实际怎么用）：
      · change_threshold  -> 构造时复制成属性，**要推**
      · ocr_interval      -> 构造时复制（还除了 1000），**要推**
      · event_end_window  -> 构造时读进 TrackManager.absence_seconds，**要推**
                             （第 12 批之前是 Detector._absence_seconds，
                               那一整套状态机搬进 track_manager 了）
      · enable_mora / enable_material / enable_artifact /
        only_foreground / log_detections
                          -> 每次 tick 都现读 self.settings，**不用推**
    """
    if det is None:
        return
    try:
        det.change_threshold = float(settings.get("change_threshold", 2.0))
    except Exception:
        pass
    try:
        det.ocr_interval = float(settings.get("ocr_interval", 150)) / 1000.0
    except Exception:
        pass
    try:
        det.tracks.absence_seconds = float(settings.get("event_end_window", 1.5))
    except Exception:
        pass


def reload_names():
    """名单改了之后让识别器重新读一遍（detector 里的集合是原地更新的）。"""
    from detector import reload_names as _reload
    return _reload()


def is_artifact_name(name):
    """这个名字该进圣遗物名单还是材料名单。

    ⚠ 用的是 Detector 上的判定方法，但**不建实例** ——
      构造 Detector 会去加载 OCR 模型，为了判一个名字不值当。
      所以是 `Detector.__new__(Detector)` 这种写法（原代码就是这么干的）。
    出错当材料处理（跟原来一致）。
    """
    try:
        from detector import Detector
        return bool(Detector._is_artifact_name(Detector.__new__(Detector), name))
    except Exception:
        return False


# ============================================================ 样本采集（开发页）
def dataset_default_path():
    """样本采集的默认目录（设置里没写就用它）。"""
    from dataset_collector import DEFAULT_PATH
    return DEFAULT_PATH


def dataset_stats(settings):
    """样本采集的统计（采了多少张 / 占多大）。"""
    from dataset_collector import DatasetCollector
    return DatasetCollector(settings).stats()


def dataset_clear(settings):
    """清空采集到的样本。"""
    from dataset_collector import DatasetCollector
    return DatasetCollector(settings).clear_all()
