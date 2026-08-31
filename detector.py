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
from generated_names import ARTIFACT_NAMES, MATERIAL_NAMES
from main_ui_model import MainUiDetector

# 圣遗物具体件名集合（精确匹配，来自用户提供的名单）
ARTIFACT_NAME_SET = set(ARTIFACT_NAMES)
# 材料名集合（精确匹配）
MATERIAL_NAME_SET = set(MATERIAL_NAMES)

# 按名字长度分组索引（纠错时只遍历长度相近的候选，避免全集合遍历导致卡顿）
_ART_INDEX = {}
for _n in ARTIFACT_NAME_SET:
    _ART_INDEX.setdefault(len(_n), []).append(_n)
_MAT_INDEX = {}
for _n in MATERIAL_NAME_SET:
    _MAT_INDEX.setdefault(len(_n), []).append(_n)

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

        # 掉落事件生命周期（防重复）：
        # 不能用“连续漏掉两帧就算消失”的方法：OCR 会偶发漏字/漏行，
        # 会把同一条仍显示的提示当成新事件而多记。这里按真实时间跟踪，
        # 并在提示稳定可见后才入账。原神掉落提示完整显示约 3.5 秒，
        # 实测中一条提示有时只能被 OCR 成功读到一次（淡出、遮挡、换行都会影响），
        # 因此新行首次识别就入账；后续帧由“行实例队列”保证不会重复入账。
        self._lifecycles = {}  # 事件身份 -> {first_seen,last_seen,hits,counted,candidates}
        self._confirm_seconds = float(self.settings.get("event_confirm_seconds", 0.15))
        self._absence_seconds = float(self.settings.get("event_end_window", 1.5))
        # 收获栏是“最多五行的队列”，同名物品可同时占多行。不能只用名称
        # 做 key，否则连续捡到 5 个同名材料会被合并而漏记。
        self._row_tracks = {}       # track id -> 单行生命周期
        self._last_row_order = []   # 上一次 OCR 中行实例的从上到下顺序
        self._next_row_track_id = 1

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
        self.change_threshold = float(self.settings.get("change_threshold", 4.0))
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
                    return None
            except Exception:
                pass
        now = time.time()
        if self.window_hwnd is None or now - self._last_win_find > 10.0:
            self._last_win_find = now
            found = find_game_window_hwnd()
            if found:
                self.window_hwnd, self.window_rect = found
        if self.window_hwnd is None:
            return None  # 还没找到游戏窗口
        try:
            # PrintWindow 截取窗口本身内容（不包含覆盖在上面的 BetterGI 窗口）
            return self.capture.grab(self.window_hwnd)
        except Exception:
            return None

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
        """【临时debug】本轮定位始终开启，写入 data/debug.log（定位后删除）"""
        return True

    def _log(self, msg):
        """【临时debug】把诊断日志写入 data/debug.log（打包版无控制台，需看文件）"""
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

    @staticmethod
    def _row_label(ev):
        """行匹配只看收益类别和名称；数量属于同一行的 OCR 读数。"""
        if ev["type"] == "mora":
            return "mora"
        if ev["type"] == "artifact":
            return "artifact"
        return "material:" + ev["name"]

    @staticmethod
    def _lcs_pairs(old_labels, new_labels):
        """返回两个有序提示行快照的最长公共子序列配对下标。"""
        rows, cols = len(old_labels), len(new_labels)
        dp = [[0] * (cols + 1) for _ in range(rows + 1)]
        for i in range(rows - 1, -1, -1):
            for j in range(cols - 1, -1, -1):
                if old_labels[i] == new_labels[j]:
                    dp[i][j] = 1 + dp[i + 1][j + 1]
                else:
                    dp[i][j] = max(dp[i + 1][j], dp[i][j + 1])
        pairs, i, j = [], 0, 0
        while i < rows and j < cols:
            if old_labels[i] == new_labels[j]:
                pairs.append((i, j))
                i, j = i + 1, j + 1
            elif dp[i + 1][j] >= dp[i][j + 1]:
                i += 1
            else:
                j += 1
        return pairs

    def _observe_row_snapshot(self, observations, frame):
        """
        5 行 FIFO 拾取 Track 生命周期（最终方案）。

        - 拾取提示建模为最多 5 行的有序 FIFO 队列。
        - Track 身份 = 有序队列连续 + identity，不用 Y 坐标（补位会变）。
        - 用"最大有序重叠"（LCS）匹配旧 Track 与当前行，保留原有 Track。
        - 只有"队尾新增"的行才创建新 Track 并入账一次。
        - 两帧完全相同、无可证明的新事件时，不新增不统计。
        - counted 的 Track 生命周期内只入账一次。
        - OCR 短暂漏读进入 MISSING，不等于结束。
        """
        now = time.time()
        if not observations:
            # 没有观察到任何行：把未超时的 Track 标记为 MISSING（不立即 END）
            for tid in list(self._row_tracks):
                st = self._row_tracks[tid]
                if st["state"] != "ended":
                    if now - st["last_seen"] > self._absence_seconds:
                        st["state"] = "ended"
                    else:
                        st["state"] = "missing"
            self._prune_tracks(now)
            return False

        # 1. 活跃 Track（未 ended、且在 absence 窗口内）
        active_ids = [tid for tid in self._last_row_order
                      if tid in self._row_tracks
                      and self._row_tracks[tid].get("state") != "ended"
                      and now - self._row_tracks[tid]["last_seen"] <= self._absence_seconds]
        old_labels = [self._row_tracks[tid]["label"] for tid in active_ids]
        new_labels = [self._row_label(ev) for ev in observations]

        # 2. 最大有序重叠（LCS）：保留原有 Track，识别队尾新增
        pairs = self._lcs_pairs(old_labels, new_labels)
        matched_new = {new_i: active_ids[old_i] for old_i, new_i in pairs}

        current_ids = []
        added = False
        for index, ev in enumerate(observations):
            label = new_labels[index]
            track_id = matched_new.get(index)
            if track_id is None:
                # 队尾新增 → 新 Track，可靠识别后立即入账一次
                track_id = self._next_row_track_id
                self._next_row_track_id += 1
                self._row_tracks[track_id] = {
                    "label": label,
                    "identity": self._event_identity(ev),
                    "event": ev,
                    "first_seen": now,
                    "last_seen": now,
                    "state": "visible",
                    "counted": False,
                }
                # 新 Track 入账一次，之后不再重复
                self._row_tracks[track_id]["counted"] = True
                added = self._apply_event(ev, frame, 0.0, use_tracker=False) or added
            else:
                # 复用旧 Track（同一行提示的连续帧）
                st = self._row_tracks[track_id]
                st["last_seen"] = now
                st["state"] = "visible"
                st["event"] = ev  # 更新最新读数
            current_ids.append(track_id)

        self._last_row_order = current_ids
        self._prune_tracks(now)
        return added

    def _prune_tracks(self, now):
        """回收 ended 或超时的 Track，避免内存增长"""
        for tid in list(self._row_tracks):
            st = self._row_tracks[tid]
            if now - st["last_seen"] > self._absence_seconds:
                st["state"] = "ended"
            if now - st["last_seen"] > 15.0:
                del self._row_tracks[tid]

    @staticmethod
    def _event_identity(ev):
        """同一条提示在 OCR 中数量/符号波动时，仍归为同一个事件。"""
        if ev["type"] == "mora":
            return "mora"
        if ev["type"] == "artifact":
            return "artifact"
        return "material:" + ev["name"]

    @staticmethod
    def _event_reading_key(ev):
        """一条完整 OCR 读数的键；用于从多次读数中选出最可信的数量。"""
        if ev["type"] == "mora":
            return ("mora", ev["amount"])
        if ev["type"] == "artifact":
            return ("artifact", 1)
        return ("material", ev["name"], ev["count"])

    def _observe_event(self, ev, frame):
        """记录一次 OCR 观察，并在事件稳定后只入账一次。

        同一事件必须跨至少两次 OCR、持续 ``_confirm_seconds`` 才会入账。
        “last_seen”按真实秒数判断，不再因两次 OCR 漏读就结束事件。
        """
        now = time.time()
        identity = self._event_identity(ev)
        state = self._lifecycles.get(identity)
        if state is None or now - state["last_seen"] > self._absence_seconds:
            state = {
                "first_seen": now,
                "last_seen": now,
                "hits": 0,
                "counted": False,
                "candidates": {},
                # 负无穷保证第一条观察一定计入样本，不能用 0：
                # 在单元测试或刚启动时 now 可能正好为 0。
                "last_sample": float("-inf"),
            }
            self._lifecycles[identity] = state

        # 自动锚点、用户区域可能同时覆盖同一条提示；同一轮扫描只算一次样本。
        if now - state["last_sample"] >= 0.08:
            reading = self._event_reading_key(ev)
            entry = state["candidates"].setdefault(reading, {"hits": 0, "event": ev, "last_seen": 0.0})
            entry["hits"] += 1
            entry["event"] = ev
            entry["last_seen"] = now
            state["hits"] += 1
            state["last_sample"] = now
        state["last_seen"] = now

        if state["counted"]:
            return False
        if state["hits"] < 2 or now - state["first_seen"] < self._confirm_seconds:
            return False

        # 选择重复出现次数最多的读数；并列时保留最新读数。
        best = max(state["candidates"].values(), key=lambda item: (item["hits"], item["last_seen"]))
        state["counted"] = True
        if self._dbg():
            self._log(f"[DBG] 生命周期确认 identity={identity!r} hits={state['hits']} event={best['event']}")
        return self._apply_event(best["event"], frame, 0.0, use_tracker=False)

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

    def _scan_region_rows(self, frame, reg):
        """在指定区域识别拾取提示行：投影找行 + 整条识别 + seen 去重统计"""
        x0, y0, x1, y1 = reg
        x0, y0 = max(0, x0), max(0, y0)
        x1 = min(frame.shape[1], x1)
        y1 = min(frame.shape[0], y1)
        if y1 - y0 < 30 or x1 - x0 < 30:
            return False
        region = frame[y0:y1, x0:x1]
        added = False
        try:
            rows = self._find_text_rows(region)
            current = set()
            # 同一行可能被背景切成多段 → 先收集所有文本，按规范化 key 去重合并
            # （保留数量：合并后仍只统计一次，但数量取第一个有效值）
            line_texts = []  # 每个元素: (规范化key, 原始text)
            for (ry0, ry1) in rows:
                crop = region[max(0, ry0 - 2):min(region.shape[0], ry1 + 3), :]
                text, score = self.ocr.recognize_line(crop)
                if not text:
                    continue
                key = self._norm_key(text)
                if not key:
                    continue
                line_texts.append((key, text.strip()))
            # 相邻相同 key 的行合并（背景把一行切碎成多段的典型情况）
            merged_texts = []
            for key, text in line_texts:
                if merged_texts and merged_texts[-1][0] == key:
                    # 同一行碎片：优先保留更"干净"（杂符更少、长度更合理）的文本，
                    # 避免带引号/破折号的片段进入解析，同时避免重复统计
                    prev_key, prev_text = merged_texts[-1]
                    if self._cleaner_text(text) > self._cleaner_text(prev_text):
                        merged_texts[-1] = (key, text)
                else:
                    merged_texts.append((key, text))
            for key, text in merged_texts:
                current.add(key)
                # 新出现（从未见过）或 消失足够久后重现（独立的新拾取）→ 统计
                if key not in self._seen or self._seen[key] >= 2:
                    ev = self._parse_pickup_text(text)
                    if self._dbg():
                        self._log(f"[DBG]   行key={key!r} text={text!r} seen={self._seen.get(key)} ev={ev}")
                    if ev is not None:
                        # seen 状态机已保证不重复，不用 tracker（同类连续拾取间隔可能很短）
                        added = self._apply_event(ev, frame, 0.0, use_tracker=False) or added
            # 更新消失计数：当前出现的=0，没出现的=+1（消失≥2帧后同文本重现视为新拾取）
            for t in current:
                self._seen[t] = 0
            for t in list(self._seen):
                if t not in current:
                    self._seen[t] += 1
            for t in list(self._seen):
                if self._seen[t] > 60:  # 太久没出现，清理（约10秒）
                    del self._seen[t]
        except Exception:
            pass
        return added

    def _parse_pickup_text(self, text):
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
            return {"type": "artifact", "count": count}
        # 2) 材料库已知材料
        if name in MATERIAL_NAME_SET or name in self.known_names:
            if not self.settings.get("enable_material", True):
                return None
            return {"type": "material", "name": name, "count": count, "category": "monster"}
        # 3) 圣遗物关键词兜底（防名单遗漏）
        if self._is_artifact_name(name):
            if not self.settings.get("enable_artifact", True):
                return None
            return {"type": "artifact", "count": count}
        # 3.5) 名单纠错（OCR 错字时，从名单找最相似的名字纠正）
        if self.settings.get("enable_artifact", True):
            corr = self._fuzzy_match(name, ARTIFACT_NAME_SET, _ART_INDEX)
            if corr:
                return {"type": "artifact", "count": count}
        if self.settings.get("enable_material", True):
            corr = self._fuzzy_match(name, MATERIAL_NAME_SET, _MAT_INDEX)
            if corr:
                return {"type": "material", "name": corr, "count": count, "category": "monster"}
        # 3.5) 大数字兜底：名字不在任何名单，但数字较大（≥20）
        #      → 极可能是摩拉被 OCR 读丢"摩"字（摩拉 ×200 只读到部分）
        #      材料的数量几乎不会 ≥20，用此区分摩拉与材料
        if count >= 20:
            if self.settings.get("enable_mora", True):
                return {"type": "mora", "name": "摩拉", "amount": count, "count": 1}
        # 4) 其它材料（不在名单里的未知文本）：
        # 原版对任何 1-10 字中文都无条件入账，导致地图地名、UI按钮文字、
        # 元素反应字（如"华光林""角色""扩散"）被误当成掉落材料。
        # 收紧：未知文本必须带数量且数量 ≥2 才入账。
        # - 真实掉落提示几乎都带数量（"破损的面具×3"）
        # - 地名/UI/状态字都是单个词、无数量的（"华光林""角色""扩散"）
        # 这样既能防漏记（带数量的采集物仍统计），又能挡住无数量的地名/UI误读。
        if not self.settings.get("enable_material", True):
            return None
        if count >= 2:
            return {"type": "material", "name": name, "count": count, "category": "monster"}
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
        """
        added = False
        if ev["type"] == "mora":
            if not use_tracker or self.tracker.is_new_event("mora"):
                self.stats.add_mora(ev["amount"])
                self.last_event = (time.time(), f"摩拉 +{ev['amount']}")
                added = True
        elif ev["type"] == "material":
            key = "material:" + ev["name"]
            if not use_tracker or self.tracker.is_new_event(key):
                self.stats.add_material(ev["name"], ev["count"], ev.get("category", "monster"))
                self.last_event = (time.time(), f"{ev['name']} ×{ev['count']}")
                added = True
        elif ev["type"] == "artifact":
            if not use_tracker or self.tracker.is_new_event("artifact"):
                self.stats.add_artifact()
                self.last_event = (time.time(), "狗粮 +1")
                added = True
        # 开发者选项：确认拾取后，后台采集 GAMEPLAY 训练样本
        if added:
            try:
                self.dataset.capture_gameplay(frame, str(ev.get("name", "")))
            except Exception:
                pass
        return added

    def _parse_text_event(self, text):
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
                return {"type": "mora", "key": "mora", "amount": int(m.group(1).replace(",", ""))}
            m = re.search(r"(\d{2,7})", text)
            if m:
                return {"type": "mora", "key": "mora", "amount": int(m.group(1).replace(",", ""))}
            return None
        # 材料/圣遗物："名字" 或 "名字×N"（整行必须是这种形式，防止把说明文字当掉落）
        # 注意：OCR 偶尔会读丢数量（如"破损的面具×2"读成"破损的面具×"），
        # 这时按 1 个算，不能整行丢弃导致漏记。
        m = re.match(r"^([\u4e00-\u9fff「」]{1,8})\s*(?:[×xX]\s*(\d{1,3}))?\s*[×xX]?$", text)
        if m:
            name = m.group(1)
            count = int(m.group(2)) if m.group(2) else 1
            # 1. 经验书等：不算收益
            if any(k in name for k in IGNORE_NAMES):
                return None
            # 2. 材料库里已知的材料
            if name in self.known_names:
                if not self.settings.get("enable_material", True):
                    return None
                return {"type": "material", "key": "material:" + name, "name": name, "count": count}
            # 3. 圣遗物（按关键词/部位后缀判断）
            if self._is_artifact_name(name):
                if not self.settings.get("enable_artifact", True):
                    return None
                return {"type": "artifact", "key": "artifact", "count": 1}
            # 4. 未知名字 → 自动注册为新材料（方便材料库持续增长）
            if m.group(2) is not None:
                if not self.settings.get("enable_material", True):
                    return None
                self._register_material(name)
                return {"type": "material", "key": "material:" + name, "name": name, "count": count}
            return None
        return None

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
        """把未知拾取物自动加入材料库（防止无限膨胀）"""
        if not self.settings.get("auto_register_material", True):
            return
        try:
            if len(self.known_names) >= MAX_MATERIALS:
                return
            mats = materials_db.load_materials()
            if any(m["name"] == name for m in mats):
                return
            mats.append({"name": name, "icon": name + ".png"})
            materials_db.save_materials(mats)
            self.known_names.add(name)
            self.last_event = (time.time(), f"📝 已自动登记新材料：{name}")
        except Exception:
            pass

    # （自动截图已移除：识别完不留任何文件在本地。手动「诊断截图」在主程序里提供。）

    def close(self):
        self.capture.close()
