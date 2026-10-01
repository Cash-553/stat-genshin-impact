# -*- coding: utf-8 -*-
"""
检测流水线（核心大脑）

流程（纯文字识别，图片识别已停用，以后需要再加回 matcher）：
屏幕捕捉
  ↓
画面变化检测（没变化就跳过，省 CPU）
  ↓
文字识别（OCR 读取掉落提示：摩拉 / 材料 / 圣遗物）
  ↓
事件去重（只有"新事件"才继续，防止重复统计）
  ↓
写入今日统计
"""
import time
import re
import cv2
import numpy as np

import materials_db
from capture import ScreenCapture
from printwindow_capture import WindowCapture, find_game_window_hwnd
from dataset_collector import DatasetCollector
from ocr_engine import OcrEngine
from stats import DailyStats, EventTracker
from detect_accounting import Accounting
from track_manager import TrackManager
from generated_names import ARTIFACT_NAMES, MATERIAL_NAMES
from main_ui_model import MainUiDetector

# 圣遗物具体件名集合（精确匹配，来自用户提供的名单）
ARTIFACT_NAME_SET = set(ARTIFACT_NAMES)
# 材料名集合（精确匹配）
MATERIAL_NAME_SET = set(MATERIAL_NAMES)

# 按名字长度分组索引（纠错时只遍历长度相近的候选，避免全集合遍历导致卡顿）
#
# ⚠ 第 11 批顺手修的：原来这里是两个**模块级 for 循环**，
#   循环变量 `_n` 会漏成模块全局 `detector._n`，而且它的值随
#   **字符串哈希随机化**每次都不同（这个进程是「新手长枪」、下个进程是
#   「电气水晶」）—— 没有任何地方用它，但会让接口快照的基线永远对不上。
#   改成函数里建 → 循环变量留在局部，`_n` 不再泄漏。
def _build_len_index(names):
    idx = {}
    for name in names:
        idx.setdefault(len(name), []).append(name)
    return idx


_ART_INDEX = _build_len_index(ARTIFACT_NAME_SET)
_MAT_INDEX = _build_len_index(MATERIAL_NAME_SET)


def reload_names():
    """从 names_db 重新载入识别名单（用户在界面上改完名单后调它）。

    名单是可以编辑的（``data/names.json``），内置那份是默认值。
    这里直接改模块级的三个变量 —— 别处都是 `from detector import xxx` 引用的，
    所以要在原地改，不能重新赋值成新对象。
    """
    try:
        import names_db
        mats = set(names_db.materials())
        arts = set(names_db.artifacts())
    except Exception:
        return
    MATERIAL_NAME_SET.clear()
    MATERIAL_NAME_SET.update(mats)
    ARTIFACT_NAME_SET.clear()
    ARTIFACT_NAME_SET.update(arts)
    # 原地改索引（别处是 `from detector import _MAT_INDEX` 引用的，不能换成新对象）
    _MAT_INDEX.clear()
    _MAT_INDEX.update(_build_len_index(MATERIAL_NAME_SET))
    _ART_INDEX.clear()
    _ART_INDEX.update(_build_len_index(ARTIFACT_NAME_SET))


# 启动时就按用户名单覆盖一次（names.json 不存在会自动从内置生成）
reload_names()

# 圣遗物套装关键词（用于把拾取物分为"狗粮"，来源：B站Wiki圣遗物套装清单）
ARTIFACT_KEYWORDS = (
    # 基础套
    "幸运儿", "冒险家", "战狂", "勇士之心", "守护之心", "武人", "流放者", "学士", "教官", "赌徒",
    "行者之心", "游医", "奇迹", "天之美赐", "长夜之誓",
    # 45套主词条流(常用)
    "被怜爱的少女", "冰风迷途的勇士", "冰之川与雪之砂", "苍白之火", "沉沦之心", "辰砂往生录",
    "炽烈的炎之魔女", "翠绿之影", "渡过烈火的贤人", "风起之日", "海染砗磲", "黑曜秘典",
    "华馆梦醒形骸记", "花海甘露之光", "黄金剧团", "回声之林夜话", "祭冰之人", "祭火之人",
    "祭雷之人", "祭水之人", "角斗士的终幕礼", "烬城勇者绘卷", "绝缘之旗印", "来歆余响",
    "乐园遗落之花", "流浪大地的乐团", "炉火融炼之心", "逆飞的流星", "平息鸣雷的尊者",
    "千岩牢固", "穹境示现之夜", "染血的骑士道", "如雷的盛怒", "沙上楼阁史话", "深廊终曲",
    "深林的记忆", "饰金之梦", "水仙之梦", "未竟的遐思", "昔日宗室之仪", "昔时之歌",
    "谐律异想断章", "影中沉凝的幻灭", "悠古的磐岩", "征服寒冬的勇士", "逐影猎人",
    "追忆之注连", "晨星与月的晓歌", "纺月的夜歌", "血中之证",
    # 别名/简写（识别时也匹配）
    "魔女", "乐团", "宗室", "染血", "苍白", "千岩", "绝缘", "追忆", "华馆", "海染",
    "辰砂", "来歆", "深林", "饰金", "楼阁", "乐园", "水仙", "甘露", "剧团", "昔时",
    "夜话", "遐思", "烬城", "断章",
    "磐岩", "翠绿", "逆飞", "角斗士", "冒险家", "战狂",
)
# 圣遗物部位后缀
ARTIFACT_SUFFIX = (
    "生之花", "死之羽", "时之沙", "空之杯", "理之冠",
    "银冠", "铜冠", "铁冠", "金冠", "玉冠",
)
# 不算任何收益的拾取物（经验书等）
IGNORE_NAMES = ("角色经验", "冒险家的经验", "流浪者的经验")
# 材料库上限（自动注册新材料时防止无限膨胀）
MAX_MATERIALS = 150


class Detector:
    def __init__(self, region, icons_dir, settings=None, stats=None):
        self.region = region  # None = 自动检测游戏窗口（不用手动框选）
        self.settings = settings or {}

        # PrintWindow 截取窗口本身内容（覆盖在游戏上的 BetterGI 提示不会混入）
        self.capture = WindowCapture()
        self.window_hwnd = None  # 游戏窗口句柄
        self.dataset = DatasetCollector(self.settings)  # AI 样本采集（开发者选项，默认关闭）
        self.ocr = OcrEngine()
        self.ui_detector = MainUiDetector()  # AI 判断是否在主界面（含2.5秒离开缓冲）
        self.stats = stats if stats is not None else DailyStats()
        self.tracker = EventTracker(
            end_window=float(self.settings.get("event_end_window", 1.5))
        )
        # 记账 / 识别日志 / 训练样本（第 11 批从 `_apply_event` 里抽出来的）。
        # ⚠ `self.dataset` 和 `self.stats` 仍然挂在本对象上（外面还在用），
        #   ledger 只是拿着同一批对象的引用。
        self.ledger = Accounting(self.stats, self.dataset, self.settings)

        # 掉落事件生命周期（防重复）：
        # 不能用“连续漏掉两帧就算消失”的方法：OCR 会偶发漏字/漏行，
        # 会把同一条仍显示的提示当成新事件而多记。这里按真实时间跟踪，
        # 并在提示稳定可见后才入账。原神掉落提示完整显示约 3.5 秒，
        # 实测中一条提示有时只能被 OCR 成功读到一次（淡出、遮挡、换行都会影响），
        # 因此新行首次识别就入账；后续帧由“行实例队列”保证不会重复入账。
        #
        # ⚠ 第 12 批（6.3）：这一整套状态机搬到 `track_manager.TrackManager` 了。
        #   收获栏是“最多五行的队列”，同名物品可同时占多行 —— 不能只用名称
        #   做 key，否则连续捡到 5 个同名材料会被合并而漏记。
        #   时钟（`time.time()`）仍然在本文件取、当参数喂进去：现有测试是
        #   `patch("detector.time.time")` 打的桩，时钟留在这儿它们才继续有效。
        self.tracks = TrackManager(
            absence_seconds=float(self.settings.get("event_end_window", 1.5)),
            report=self._report_new_track,
        )

        # 提示栏锚点记忆（思路一）：
        # 首次找到「获得」标题后，记住其下方的提示栏区域，即使「获得」随后消失
        # 也继续用这个区域识别下面的收获物（避免锚点消失导致漏记）。
        # "获得"每刷新一次，extend 到期时间；到期后清空，重新定位。
        self._anchor_region = None   # (x0, y0, x1, y1) 提示栏区域
        self._anchor_extend = 0.0    # "获得"最近被看到的时间
        self._anchor_expire = 4.0    # 秒："获得"消失这么久后丢弃记忆,重新找

        # 自动窗口模式状态
        self.auto_window = region is None
        self.window_rect = None          # 游戏窗口位置
        self._last_win_find = 0.0
        self._last_full_scan = 0.0       # 上次全屏扫描的时间

        # 性能控制参数
        self.change_threshold = float(self.settings.get("change_threshold", 2.0))
        self.prev_small = None
        self.last_full_check = 0.0
        self.safety_interval = float(self.settings.get("safety_interval", 1.5))

        # 最近一次识别到的事件（给界面显示用）
        self.last_event = None  # (时间戳, 描述文字)
        self._last_unmatched_log = 0.0  # 上次记录"识别不到"画面的时间
        self._last_ocr = 0.0            # 上次OCR的时间（文字识别节流用）
        self.known_names = {m["name"] for m in materials_db.load_materials()}
        # 文字识别为主：每次完整检测最多隔多久做一次OCR（毫秒）
        self.ocr_interval = float(self.settings.get("ocr_interval", 150)) / 1000.0

    # ---------- 主循环 ----------

    def tick(self):
        """
        检测一次。返回 True 表示这次统计到了新收益。
        调用方每秒调用几次即可（内部会自动省电跳过）。
        """
        frame = self._grab()
        if frame is None:
            return False
        score = self._change_score(frame)
        now = time.time()

        # 【临时debug】记录变化分数 / 是否被跳过
        if self._dbg():
            self._log(f"[DBG] tick score={score:.3f} thr={self.change_threshold} skip={score < self.change_threshold and now - self.last_full_check < self.safety_interval}")

        # 画面没变化，且最近刚完整检测过 → 跳过（省 CPU）
        if score < self.change_threshold and now - self.last_full_check < self.safety_interval:
            return False

        self.last_full_check = now
        return self._full_detect(frame)

    def _grab(self):
        """抓取画面：手动区域 或 自动游戏窗口"""
        if not self.auto_window:
            return self.capture.grab(self.region)
        # 只在前台时识别：若开启且当前前台不是原神，跳过（不截图识别）
        if self.settings.get("only_foreground", True):
            try:
                from capture import is_genshin_foreground
                if not is_genshin_foreground():
                    # ⚠ 这是**正常跳过**（用户切到别的窗口了），
                    #   不能算「抓不到画面」—— 否则一切出去就报错，纯噪音
                    self._grab_miss = 0
                    return None
            except Exception:
                pass
        now = time.time()
        if self.window_hwnd is None or now - self._last_win_find > 10.0:
            self._last_win_find = now
            found = find_game_window_hwnd()
            # ⚠ 找不到就**必须把旧句柄清掉**。
            #   原来只在 found 为真时才赋值 —— 游戏重启 / 关掉再开之后，
            #   旧句柄一直留着，之后每一轮都拿着一个死句柄去截图；
            #   截图失败又被下面的 except 吞掉、return None，
            #   界面上还显示「正在监测」，实际一个都不识别。
            #   这就是用户反馈的「突然不识别」。
            if found:
                self.window_hwnd, self.window_rect = found
            else:
                self.window_hwnd = None
                self.window_rect = None
        if self.window_hwnd is None:
            self._grab_miss = getattr(self, "_grab_miss", 0) + 1
            return None  # 还没找到游戏窗口
        try:
            frame = self.capture.grab(self.window_hwnd)
        except Exception:
            frame = None
        if frame is None:
            # 这一轮没抓到（窗口关了 / 最小化 / 句柄失效）→ 清掉句柄，
            # 下一轮会重新去找；否则会一直卡在死句柄上
            self.window_hwnd = None
            self.window_rect = None
            self._grab_miss = getattr(self, "_grab_miss", 0) + 1
            return None
        self._grab_miss = 0
        return frame

    def _change_score(self, frame_bgr):
        """
        计算画面和上一帧的差异程度（0~255 均值）。
        只对"收获行区域"做变化检测（而非整张图），大幅降低 CPU 占用：
        - resize 的成本只在收获行小区域上
        - 只有收获行区域变化才触发识别（主界面其他地方的动态不影响）
        """
        try:
            x0, y0, x1, y1 = self._pickup_region(frame_bgr)
            sub = frame_bgr[y0:y1, x0:x1]
        except Exception:
            sub = frame_bgr
        small = cv2.resize(sub, (64, 48), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        if self.prev_small is None:
            self.prev_small = gray
            return 0.0
        diff = cv2.absdiff(gray, self.prev_small)
        self.prev_small = gray
        return float(diff.mean())

    # ---------- 完整检测 ----------

    def _dbg(self):
        """调试日志开关：默认关闭。

        打开方式：设置 → 关于 → 开发者选项 → 自动保存诊断截图。
        关着的时候下面那些 [DBG] 日志一行都不写（以前是常开，
        每轮检测都往 data/debug.log 写，既费性能又一直涨）。
        """
        try:
            return bool((getattr(self, "settings", None) or {}).get("save_debug", False))
        except Exception:
            return False

    def _log(self, msg):
        """把诊断日志写入 data/debug.log（打包版没有控制台，只能看文件）"""
        try:
            from paths import app_dir
            p = app_dir() / "data" / "debug.log"
            import io
            with io.open(str(p), "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except Exception:
            pass
        try:
            print(msg)
        except Exception:
            pass

    def _full_detect(self, frame_bgr):
        added = False
        now = time.time()
        frame = frame_bgr

        # 判断是否在主界面（AI 模型，含 2.5 秒离开缓冲）
        try:
            in_ui = self.ui_detector.in_main_ui(frame)
            if self._dbg():
                self._log(f"[DBG] AI主界面 sim={self.ui_detector.last_sim:.3f} thr={self.ui_detector._threshold} in_ui={in_ui}")
            if not in_ui:
                return False  # 非主界面，不识别（避免把界面文字当掉落）
        except Exception:
            pass

        # ---- 主识别（每 ocr_interval 一次）----
        if now - self._last_ocr >= self.ocr_interval:
            self._last_ocr = now
            if self._dbg():
                self._log(f"[DBG] full_detect 触发OCR，走 {'自动窗口锚点' if self.auto_window else '手动区域'}")
            if self.auto_window:
                # 自动窗口模式：识别左下角拾取提示（提示出现=确定已拾取）
                added = self._scan_left_pickups(frame) or added
            else:
                # 手动区域模式：区域小，直接完整识别
                added = self._scan_full(frame) or added

        return added

    # ---------- 左下角拾取提示识别 ----------

    def _pickup_region(self, frame):
        """左下角拾取提示区域（1080p 基准 x0-500, y500-800，等比缩放）"""
        h, w = frame.shape[:2]
        s = h / 1080.0
        x0, y0 = 0, int(500 * s)
        x1 = min(w, int(500 * s))
        y1 = min(h, int(800 * s))
        return x0, y0, x1, y1

    def _find_text_rows(self, region_bgr):
        """用水平投影找区域内的文字行带，返回 [(y0, y1), ...]（从上到下）"""
        gray = cv2.cvtColor(region_bgr, cv2.COLOR_BGR2GRAY)
        _, binimg = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        row_sums = (binimg > 0).sum(axis=1)
        rows = []
        in_row = False
        start = 0
        for y, s in enumerate(row_sums):
            if s > 3:
                if not in_row:
                    start = y
                    in_row = True
            else:
                if in_row:
                    rows.append((start, y - 1))
                    in_row = False
        if in_row:
            rows.append((start, len(row_sums) - 1))
        # 合并相邻太近的行带（同一行文字可能有小空隙）
        merged = []
        for r in rows:
            if merged and r[0] - merged[-1][1] <= 6:
                merged[-1] = (merged[-1][0], max(merged[-1][1], r[1]))
            else:
                merged.append(r)
        return merged

    @staticmethod
    def _norm_key(text):
        """
        规范化文本作为去重 key（同一行内容必须归到同一个 key，防止多记）：
        - 去掉所有空格
        - 统一 × 符号（OCR 输出不稳定：× x X 都归一为 x）
        - 去掉 OCR 常带出的杂符（中文引号、弯引号、句号、点、波浪线等），
          防止 `混沌机关×3` 与 `"混沌机关×3` 被当成两个 key
        - 保留数量和汉字（数量不能丢，要真实累计）
        """
        t = re.sub(r"\s+", "", text or "")
        # 只保留：汉字、数字、x（×归一后）、以及常见数量分隔
        t = re.sub(r"[^\u4e00-\u9fff0-9xX×]", "", t)
        return t.replace("×", "x").replace("X", "x").replace("x", "x")

    @staticmethod
    def _cleaner_text(text):
        """
        文本"干净度"评分：杂符（引号/破折号/符号等）越少、汉字越多，越干净。
        用于同一行被切碎成多段时，挑选最完整干净的一段来解析统计。
        """
        if not text:
            return -1
        chars = text.strip()
        total = max(1, len(chars))
        # 干净字符：汉字 + 数字 + x + ×
        clean = len(re.findall(r"[\u4e00-\u9fff0-9xX×]", chars))
        return clean / total

    def _scan_left_pickups(self, frame):
        """
        识别拾取提示（确定已拾取），多区域同时识别（提高准确率）：
        1. "获得"锚点定位：找到提示栏标题"获得"，其下方就是提示行
        2. 用户框选位置（第一次使用时框选的提示栏区域）
        3. 兜底：固定左下角区域
        所有区域共享 seen 去重（同一提示不会重复统计）。
        """
        added = False
        now = time.time()
        regions = []

        # —— 思路一：锚点记忆 ——
        # "获得"标题通常比下面那几列收获物消失得更快。
        # 优先用已记住的提示栏区域识别（即使"获得"已消失）；
        # 只要"获得"还能找到，就刷新记忆和到期时间；很久没找到则丢弃记忆重新定位。
        anchor_ok = self._anchor_region is not None and now - self._anchor_extend < self._anchor_expire
        if self._dbg():
            self._log(f"[DBG] scan_left: anchor_ok={anchor_ok} anchor={self._anchor_region}")
        if anchor_ok:
            regions.append(self._anchor_region)
            # 记忆还生效时，仍尝试重新定位"获得"来续期（OCR 有节流，不会太频繁）
            cur = self._find_anchor_region(frame)
            if self._dbg():
                self._log(f"[DBG]   续期找获得 cur={cur}")
            if cur:
                self._anchor_region = cur
                self._anchor_extend = now
        else:
            new_anchor = self._find_anchor_region(frame)
            if self._dbg():
                self._log(f"[DBG]   冷启动找获得 new_anchor={new_anchor}")
            if new_anchor:
                self._anchor_region = new_anchor
                self._anchor_extend = now
                regions.append(new_anchor)
            elif self._anchor_region is not None:
                # 找不到"获得"，但记忆过期前收获物可能还在显示：多沿用一小段
                if now - self._anchor_extend < self._anchor_expire + 2.0:
                    regions.append(self._anchor_region)
                else:
                    self._anchor_region = None

        sr = self.settings.get("region")
        if sr and self.window_rect:
            fr = self._region_to_frame(sr)
            if fr:
                regions.append(fr)
        if not regions:
            regions.append(self._pickup_region(frame))
        if self._dbg():
            self._log(f"[DBG]   最终识别区域数={len(regions)} regions={regions}")
        # 多个重叠区域会把同一行 OCR 两遍，反而破坏“行队列”判断。
        # 锚点区域优先；没有锚点时才使用手动区域/固定区域。
        if regions:
            added = self._scan_region_boxes(frame, regions[0]) or added
        return added

    def _scan_region_boxes(self, frame, reg):
        """
        用 OCR 自动分行识别收获行（替代易失效的"投影找行"法）。
        RapidOCR 的 recognize_boxes 会自动检测文字框位置并逐条识别，
        能正确处理收获行区域的背景干扰。
        返回是否统计到新收益（沿用 seen 去重，保留真实数量）。
        """
        x0, y0, x1, y1 = reg
        x0, y0 = max(0, x0), max(0, y0)
        x1 = min(frame.shape[1], x1)
        y1 = min(frame.shape[0], y1)
        if y1 - y0 < 30 or x1 - x0 < 30:
            return False
        region = frame[y0:y1, x0:x1]
        added = False
        try:
            lines = self.ocr.recognize_boxes(region)
            if not lines:
                return added
            # 收集所有文本（排除"获得"标题），按 y 排序
            texts = []
            for text, score, box in lines:
                if not text or "获得" in text:
                    continue
                bx, by, bw, bh = box
                texts.append((by, text.strip()))
            # 把同一行被切成多段的，按规范化 key 相邻去重合并（防多记，保留数量）
            texts.sort(key=lambda t: t[0])
            line_texts = []
            for by, text in texts:
                key = self._norm_key(text)
                if not key:
                    continue
                if line_texts and line_texts[-1][2] == key and by - line_texts[-1][0] < 30:
                    # 同一行碎片（y 接近 且 key 相同）：保留更干净的一段
                    if self._cleaner_text(text) > self._cleaner_text(line_texts[-1][3]):
                        line_texts[-1] = (by, by, key, text)
                    continue
                line_texts.append((by, by, key, text))
            # 先组成一整个“从上到下的提示行快照”，再按行队列比对。
            # 这样同名材料的多行不会被合并成一条。
            observations = []
            for by, _, key, text in line_texts:
                ev = self._parse_pickup_text(text)
                if self._dbg():
                    self._log(f"[DBG]   boxes行key={key!r} text={text!r} ev={ev}")
                if ev is not None:
                    observations.append(ev)
            added = self._observe_row_snapshot(observations, frame) or added
        except Exception:
            pass
        return added

    def _observe_row_snapshot(self, observations, frame):
        """5 行 FIFO 拾取 Track 生命周期 —— 第 12 批搬到 `track_manager.TrackManager`。

        ⚠ 这个方法**只留一行转发**（对外表面不变：`test_event_lifecycle.py`、
          `_morph\\test_counting.py`、`_morph\\test_detector_tracks.py` 都还在调它）。
        ⚠ 时钟在这儿取、当参数传进去 —— 现有测试是 `patch("detector.time.time")`
          打的桩，时钟留在这边它们才继续有效。
        """
        return self.tracks.observe(observations, frame, time.time())

    def _report_new_track(self, ev, frame):
        """Track 状态机判定「这是一次新拾取」时回调到这里 —— 只负责入账。

        原来这一句是内联在 `_observe_row_snapshot` 里的
        `self._apply_event(ev, frame, 0.0, use_tracker=False)`：
        `use_tracker=False` 是因为"新 Track"这件事本身已经保证了不重复，
        不需要再过一遍时间窗口去重。
        """
        return self._apply_event(ev, frame, 0.0, use_tracker=False)

    def _find_anchor_region(self, frame):
        """在左下角区域找"获得"标题，返回其下方提示栏区域；找不到返回 None"""
        try:
            h, w = frame.shape[:2]
            s = h / 1080.0
            x0, y0 = 0, int(360 * s)
            x1 = min(w, int(640 * s))
            y1 = min(h, int(840 * s))
            region = frame[y0:y1, x0:x1]
            rows = self._find_text_rows(region)
            for (ry0, ry1) in rows:
                crop = region[max(0, ry0 - 2):min(region.shape[0], ry1 + 3), :]
                text, _ = self.ocr.recognize_line(crop)
                if text and "获得" in text:
                    # 提示栏 = "获得"行下方到区域底部
                    return (x0, y0 + ry1 + 2, x1, y1)
        except Exception:
            pass
        return None

    def _region_to_frame(self, region):
        """把用户框选的屏幕坐标区域换算成窗口内坐标（自动窗口模式）"""
        try:
            if not self.window_rect:
                return None
            wx, wy = self.window_rect["x"], self.window_rect["y"]
            x0 = region["x"] - wx
            y0 = region["y"] - wy
            x1 = x0 + region["w"]
            y1 = y0 + region["h"]
            if x1 <= x0 or y1 <= y0:
                return None
            return (x0, y0, x1, y1)
        except Exception:
            return None

    def _parse_pickup_text(self, text):
        """包一层：把**原始 OCR 文字**塞进结果里。

        为什么要：识别日志要记"这一笔是被哪段文字骗出来的"，
        但内部有十几个 return，逐个加字段容易漏。包一层最省事。
        """
        ev = self._parse_pickup_text_inner(text)
        if ev is not None:
            ev.setdefault("raw", (text or "").strip())
        return ev

    def _filter_allows(self, kind, name=""):
        """黑名单 / 白名单：认出来了要不要记账。

        kind = "material" / "artifact"
        规则（白名单优先）：
            白名单开着且非空 -> 只记名单里的
            黑名单开着       -> 名单里的一律不记
        名单为空且白名单开着 = 什么都不记（设置页会在离开时提醒并关掉它）
        """
        try:
            import filters_db
            return filters_db.allows(self.settings, kind, name)
        except Exception:
            return True          # 读不到名单就别拦，宁可能记也别丢数据

    def _parse_pickup_text_inner(self, text):
        """
        解析一行拾取提示："名称 × 数量"（原神里 × 符号偏小，OCR 可能读丢或读错）。
        支持 "名称×2" / "名称 × 2" / "名称 2" / 纯"名称"（数量=1）。
        分类：摩拉 / 怪物掉落物 / 圣遗物(狗粮) / 普通材料（自动登记）。
        """
        if not text:
            return None
        t = text.strip()
        if not t or "获得" in t:
            return None  # "获得"是提示栏标题，不是拾取物
        # 摩拉："摩拉 ×200" / "摩拉×200" / "摩拉 200"
        # 也兼容 OCR 把"摩拉"读成近似错字（魔拉/磨拉/莫拉 等）
        if "摩" in t:
            m = re.search(r"[×xX]?\s*([\d,]{2,6})", t)
            if m:
                amount = int(m.group(1).replace(",", ""))
                if not self.settings.get("enable_mora", False):
                    return None  # 摩拉开关：默认关（用户要统计就打开）
                if self._mora_over_limit(amount, t):
                    return None  # 读数异常（多半是伤害数字叠上来），当误读丢掉
                return {"type": "mora", "name": "摩拉", "amount": amount, "count": 1}
            return None
        # 材料 / 圣遗物："名称" + 可选 [×] + 可选数量
        # 注意：游戏掉落提示会显示「」书名号，正则需允许这些字符
        m = re.match(r"^([\u4e00-\u9fff「」]{1,10})\s*[×xX]?\s*(\d{1,4})?$", t)
        if not m:
            return None
        name = m.group(1)
        count = int(m.group(2)) if m.group(2) else 1
        # 经验书等：不算收益。用宽松匹配（含"经验"即忽略，覆盖 OCR 错字如"鱼色经验"）
        if any(k in name for k in IGNORE_NAMES) or "经验" in name:
            return None  # 经验书等：不算收益
        # 1) 先精确匹配圣遗物名单（最准，防止误判为材料）
        if name in ARTIFACT_NAME_SET:
            if not self.settings.get("enable_artifact", True):
                return None
            if not self._filter_allows("artifact", name):
                return None
            return {"type": "artifact", "count": count}
        # 2) 材料库已知材料
        if name in MATERIAL_NAME_SET:
            if not self.settings.get("enable_material", True):
                return None
            if not self._filter_allows("material", name):
                return None
            return {"type": "material", "name": name, "count": count, "category": "monster"}
        # 3) 圣遗物关键词兜底（防名单遗漏）
        if self._is_artifact_name(name):
            if not self.settings.get("enable_artifact", True):
                return None
            if not self._filter_allows("artifact", name):
                return None
            return {"type": "artifact", "count": count}
        # 3.5) 名单纠错（OCR 错字时，从名单找最相似的名字纠正）
        if self.settings.get("enable_artifact", True):
            corr = self._fuzzy_match(name, ARTIFACT_NAME_SET, _ART_INDEX)
            if corr and self._filter_allows("artifact", corr):
                return {"type": "artifact", "count": count}
        if self.settings.get("enable_material", True):
            corr = self._fuzzy_match(name, MATERIAL_NAME_SET, _MAT_INDEX)
            if corr and self._filter_allows("material", corr):
                return {"type": "material", "name": corr, "count": count, "category": "monster"}
        # 3.5) 大数字兜底：名字不在任何名单，但数字较大（≥20）
        #      → 极可能是摩拉被 OCR 读丢"摩"字（摩拉 ×200 只读到部分）
        #      材料的数量几乎不会 ≥20，用此区分摩拉与材料
        if count >= 20:
            if self.settings.get("enable_mora", True):
                if self._mora_over_limit(count, t):
                    return None
                return {"type": "mora", "name": "摩拉", "amount": count, "count": 1}
        # 4) 不在任何名单里的 → **不登记**（只记日志）
        #
        #    以前这里是"带数量（≥2）就入账"，结果 OCR 认错的名字
        #    （编编花蜜 / 适 / 塑等化形 …）全都进了统计和材料库。
        #    现在一律不登记 —— 名单已经是完整的（574 材料 + 299 圣遗物），
        #    认不出来的基本就是读错了。
        self._log_rejected(name, count, t)
        return None

    def _scan_full(self, frame_bgr):
        """全屏识别兜底（手动区域主用），返回是否统计到新收益"""
        frame = frame_bgr
        if self.auto_window and frame.shape[1] > 1400:
            s = 1400.0 / frame.shape[1]
            frame = cv2.resize(frame, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        added = False
        try:
            lines = self.ocr.recognize_boxes(frame)
            if not lines:
                return added
            # 把同一行的文字合并后再解析
            rows = []
            for text, score, box in lines:
                bx, by, bw, bh = box
                cy = by + bh / 2
                placed = False
                for r in rows:
                    if abs(r["cy"] - cy) < max(14, bh * 0.7):
                        r["items"].append((bx, text))
                        x0 = min(r["box"][0], bx)
                        y0 = min(r["box"][1], by)
                        x1 = max(r["box"][0] + r["box"][2], bx + bw)
                        y1 = max(r["box"][1] + r["box"][3], by + bh)
                        r["box"] = (x0, y0, x1 - x0, y1 - y0)
                        placed = True
                        break
                if not placed:
                    rows.append({"cy": cy, "items": [(bx, text)], "box": (bx, by, bw, bh)})
            for r in rows:
                r["items"].sort(key=lambda it: it[0])
                combined = "".join(t for x, t in r["items"])
                ev = self._parse_text_event(combined)
                if ev is None:
                    continue
                added = self._apply_event(ev, frame_bgr, 0.9) or added
        except Exception:
            pass
        return added

    def _apply_event(self, ev, frame, score=0.0, use_tracker=True):
        """
        把解析出的事件写入统计。返回是否统计到了新收益。
        use_tracker=True：走时间窗口去重（手动区域识别用）
        use_tracker=False：由调用方（seen 状态机）保证"新出现才统计"，
                           用于同类连续拾取（间隔可能小于去重窗口，不能用 tracker）

        ⚠ 第 11 批（6.1 + 6.2）之后这个方法**只管"是不是新事件"**：
          记账 / 识别日志 / 训练样本都交给 `self.ledger`（`detect_accounting.Accounting`）。
          原来这三件事全挤在这里，想改日志格式都得动识别代码。
          抽的时候行为一个字没改 —— 有 `_morph\\test_detector_apply.py`
          （29 条断言）盯着。
        """
        added = False
        if ev["type"] == "mora":
            if not use_tracker or self.tracker.is_new_event("mora"):
                self.last_event = self.ledger.record(
                    ev, frame, self._record_source(use_tracker))
                added = True
        elif ev["type"] == "material":
            key = "material:" + ev["name"]
            if not use_tracker or self.tracker.is_new_event(key):
                self.last_event = self.ledger.record(
                    ev, frame, self._record_source(use_tracker))
                added = True
        elif ev["type"] == "artifact":
            if not use_tracker or self.tracker.is_new_event("artifact"):
                self.last_event = self.ledger.record(
                    ev, frame, self._record_source(use_tracker))
                added = True
        return added

    @staticmethod
    def _record_source(use_tracker):
        """识别日志里的「来源」那栏（原来是内联在三处调用里的字符串）"""
        return "区域扫描" if use_tracker else "行队列"

    def _parse_text_event(self, text):
        """包一层：同样把原始 OCR 文字塞进结果里（给识别日志用）"""
        ev = self._parse_text_event_inner(text)
        if ev is not None:
            ev.setdefault("raw", (text or "").strip())
        return ev

    def _parse_text_event_inner(self, text):
        """
        从一行文字里解析掉落事件。
        返回 {"type": "mora"|"material"|"artifact", ...} 或 None
        """
        if not text:
            return None
        text = text.strip()
        # 摩拉："摩拉×400" / "摩拉 +7050"
        if "摩拉" in text:
            if not self.settings.get("enable_mora", True):
                return None
            m = re.search(r"[×xX+]\s*([\d,]{2,})", text)
            if m:
                amt = int(m.group(1).replace(",", ""))
                if self._mora_over_limit(amt, text):
                    return None
                return {"type": "mora", "key": "mora", "amount": amt}
            m = re.search(r"(\d{2,7})", text)
            if m:
                amt = int(m.group(1).replace(",", ""))
                if self._mora_over_limit(amt, text):
                    return None
                return {"type": "mora", "key": "mora", "amount": amt}
            return None
        # 材料/圣遗物："名字" 或 "名字×N"（整行必须是这种形式，防止把说明文字当掉落）
        # 注意：OCR 偶尔会读丢数量（如"破损的面具×2"读成"破损的面具×"），
        # 这时按 1 个算，不能整行丢弃导致漏记。
        m = re.match(r"^([\u4e00-\u9fff「」]{1,8})\s*(?:[×xX]\s*(\d{1,3}))?\s*[×xX]?$", text)
        if m:
            name = m.group(1)
            count = int(m.group(2)) if m.group(2) else 1
            # 1. 经验书等：不算收益
            if any(k in name for k in IGNORE_NAMES) or "经验" in name:
                return None
            # 2. 名单里已知的材料
            #    MATERIAL_NAME_SET = 识别名单（generated_names.py，574 个）
            #    self.known_names   = 材料库（data/materials.json）
            #    两个都查 —— 只查材料库的话，名单里有但库里的会漏认
            if name in MATERIAL_NAME_SET:
                if not self.settings.get("enable_material", True):
                    return None
                if not self._filter_allows("material", name):
                    return None
                return {"type": "material", "key": "material:" + name, "name": name, "count": count}
            # 3. 圣遗物（按关键词/部位后缀判断）
            if self._is_artifact_name(name):
                if not self.settings.get("enable_artifact", True):
                    return None
                if not self._filter_allows("artifact", name):
                    return None
                return {"type": "artifact", "key": "artifact", "count": 1}
            # 3.5 名单纠错：OCR 读错字时，从名单里找最像的纠正
            if self.settings.get("enable_material", True):
                corr = self._fuzzy_match(name, MATERIAL_NAME_SET, _MAT_INDEX)
                if corr and self._filter_allows("material", corr):
                    return {"type": "material", "key": "material:" + corr,
                            "name": corr, "count": count}
                corr = self._fuzzy_match(name, ARTIFACT_NAME_SET, _ART_INDEX)
                if corr and self._filter_allows("artifact", corr):
                    return {"type": "artifact", "key": "artifact", "count": 1}
            # 4. 不在任何名单里的 → **不登记**
            #
            #    以前这里是"未知名字就自动登记进材料库"，结果 OCR 认错的
            #    也全被记进去（编编花蜜 / 适 / 塑等化形 …）。现在只记进
            #    识别日志，方便你事后看"漏掉了什么"，但不进统计、不入库。
            self._log_rejected(name, count, text)
            return None
        return None

    def _log_rejected(self, name, count, raw):
        """识别到但不在名单里的 —— 记进日志，但不统计、不登记。

        这样你翻日志能看出"哪些名字被丢掉了"，需要的话再手动加进名单。

        ⚠ 第 11 批：写日志的动作搬到 `Accounting.log_rejected` 了，
          这里只留"什么算未登记"这个判断。
        """
        self.ledger.log_rejected(name, count, raw)

    def _mora_over_limit(self, amount, raw=""):
        """摩拉单次读数是否超过「计数上限」—— 超了就当误读丢掉。

        为什么要这道闸（用户提的需求）：
            战斗时角色的**伤害数字**会跟「获得」栏的摩拉读数叠在一块儿，
            OCR 可能一次读出「摩拉 12500」这种，一笔就把摩拉统计顶上天
            （几万、几十万都出现过）。加了上限之后，超过的读数直接丢掉、不统计。

        上限从设置读（`mora_max_amount`，默认 3000，设 0 = 不限制）；
        **每次都现读** `self.settings`，所以用户在设置里改完立刻生效，
        不需要「推给正在跑的识别器」那一步。

        返回 True = 超限、调用方应当丢弃这条读数（同时往识别日志里记一笔，
        日志的「来源」列会写「未统计（超过单次上限 N）」，方便事后核对）。
        """
        try:
            limit = int(float(self.settings.get("mora_max_amount", 3000) or 0))
        except Exception:
            limit = 3000
        if limit <= 0 or amount <= limit:
            return False
        try:
            self.ledger.log_dropped(
                "摩拉", "", 1, amount, raw, f"未统计（超过单次上限 {limit}）")
        except Exception:
            pass
        return True

    def _is_artifact_name(self, name):
        """判断一个拾取物名字是否是圣遗物"""
        if any(k in name for k in ARTIFACT_KEYWORDS):
            return True
        if any(name.endswith(s) for s in ARTIFACT_SUFFIX):
            return True
        return False

    def _fuzzy_match(self, name, name_set, index=None):
        """
        名单纠错：识别出的名字不在名单里时，从名单中找最相似的正确名字返回。

        优化：用"按长度分组"的索引，只遍历长度相近的候选，避免对整份名单
        （材料 574 + 圣遗物 299）逐个算相似度导致卡顿。
        相似度阈值 0.6（比一字差的 0.75 更宽松，让识别到的东西尽量归到名单内）。
        找不到返回 None。
        """
        if not name or not name_set:
            return None
        n = len(name)
        best = None
        best_score = 0.0
        if index is None:
            index = {}
            for cand in name_set:
                index.setdefault(len(cand), []).append(cand)
        # 只遍历长度差 ≤ 2 的候选
        for ln in range(n - 2, n + 3):
            for cand in index.get(ln, []):
                score = self._sim(name, cand)
                if score > best_score:
                    best_score = score
                    best = cand
        if best is not None and best_score >= 0.6:
            return best
        return None

    @staticmethod
    def _sim(a, b):
        """简易相似度：最长公共子序列占比"""
        m, n = len(a), len(b)
        dp = [[0] * (n + 1) for _ in range(m + 1)]
        for i in range(1, m + 1):
            for j in range(1, n + 1):
                if a[i - 1] == b[j - 1]:
                    dp[i][j] = dp[i - 1][j - 1] + 1
                else:
                    dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])
        lcs = dp[m][n]
        return lcs / max(m, n)

    def _register_material(self, name):
        """【已停用】以前会把不认识的拾取物自动加进材料库。

        为什么停用：OCR 认错的名字（编编花蜜 / 适 / 塑等化形 …）也被当成
        "新材料"登记进去，材料库攒了一堆错词。现在认不出来的名字
        **既不统计也不登记**，只写进识别日志（`data/识别日志/`，一次运行一个文件）供事后查看。

        留着这个空函数是为了兼容旧调用点；要恢复的话把内容加回来即可。
        """
        return

    # （自动截图已移除：识别完不留任何文件在本地。手动「诊断截图」在主程序里提供。）

    def close(self):
        self.capture.close()
