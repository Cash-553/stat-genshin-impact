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
from ocr_engine import OcrEngine
from stats import DailyStats, EventTracker

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

        self.capture = ScreenCapture()
        self.ocr = OcrEngine()
        self.stats = stats if stats is not None else DailyStats()
        self.tracker = EventTracker(
            end_window=float(self.settings.get("event_end_window", 1.5))
        )

        # 左下角拾取提示状态机（防重复）：
        # 记录每个提示文本的"消失计数"，新出现（或消失≥2帧后重现）= 新拾取才统计
        self._seen = {}  # text -> 连续消失帧数（0=正在显示）

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

        # 画面没变化，且最近刚完整检测过 → 跳过（省 CPU）
        if score < self.change_threshold and now - self.last_full_check < self.safety_interval:
            return False

        self.last_full_check = now
        return self._full_detect(frame)

    def _grab(self):
        """抓取画面：手动区域 或 自动游戏窗口"""
        if not self.auto_window:
            return self.capture.grab(self.region)
        now = time.time()
        if self.window_rect is None or now - self._last_win_find > 10.0:
            self._last_win_find = now
            from capture import find_game_window
            rect = find_game_window()
            if rect:
                self.window_rect = rect
        if self.window_rect is None:
            return None  # 还没找到游戏窗口
        try:
            return self.capture.grab(self.window_rect)
        except Exception:
            return None

    def _change_score(self, frame_bgr):
        """计算画面和上一帧的差异程度（0~255 均值）"""
        small = cv2.resize(frame_bgr, (64, 48), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        if self.prev_small is None:
            self.prev_small = gray
            return 0.0
        diff = cv2.absdiff(gray, self.prev_small)
        self.prev_small = gray
        return float(diff.mean())

    # ---------- 完整检测 ----------

    def _full_detect(self, frame_bgr):
        added = False
        now = time.time()
        frame = frame_bgr

        # ---- 主识别（每 ocr_interval 一次）----
        if now - self._last_ocr >= self.ocr_interval:
            self._last_ocr = now
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
        """规范化文本作为去重 key：去掉所有空格、统一 × 符号（OCR 输出不稳定）"""
        t = re.sub(r"\s+", "", text or "")
        return t.replace("×", "x").replace("X", "x").replace("x", "x")

    def _scan_left_pickups(self, frame):
        """
        识别拾取提示（确定已拾取），多区域同时识别（提高准确率）：
        1. "获得"锚点定位：找到提示栏标题"获得"，其下方就是提示行
        2. 用户框选位置（第一次使用时框选的提示栏区域）
        3. 兜底：固定左下角区域
        所有区域共享 seen 去重（同一提示不会重复统计）。
        """
        added = False
        regions = []
        anchor = self._find_anchor_region(frame)
        if anchor:
            regions.append(anchor)
        sr = self.settings.get("region")
        if sr and self.window_rect:
            fr = self._region_to_frame(sr)
            if fr:
                regions.append(fr)
        if not regions:
            regions.append(self._pickup_region(frame))
        for reg in regions:
            added = self._scan_region_rows(frame, reg) or added
        return added

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
            for (ry0, ry1) in rows:
                crop = region[max(0, ry0 - 2):min(region.shape[0], ry1 + 3), :]
                text, score = self.ocr.recognize_line(crop)
                if not text:
                    continue
                key = self._norm_key(text)
                if not key:
                    continue
                current.add(key)
                # 新出现（从未见过）或 消失足够久后重现（独立的新拾取）→ 统计
                if key not in self._seen or self._seen[key] >= 2:
                    ev = self._parse_pickup_text(text.strip())
                    if ev is not None:
                        # seen 状态机已保证不重复，不用 tracker（同类连续拾取间隔可能很短）
                        added = self._apply_event(ev, frame, score, use_tracker=False) or added
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
        if "摩拉" in t:
            m = re.search(r"[×xX]?\s*([\d,]{2,6})", t)
            if m:
                amount = int(m.group(1).replace(",", ""))
                if not self.settings.get("enable_mora", False):
                    return None  # 摩拉开关：默认关（用户要统计就打开）
                return {"type": "mora", "name": "摩拉", "amount": amount, "count": 1}
            return None
        # 材料 / 圣遗物："名称" + 可选 [×] + 可选数量
        m = re.match(r"^([\u4e00-\u9fff]{1,10})\s*[×xX]?\s*(\d{1,4})?$", t)
        if not m:
            return None
        name = m.group(1)
        count = int(m.group(2)) if m.group(2) else 1
        if any(k in name for k in IGNORE_NAMES):
            return None  # 经验书等：不算收益
        if name in self.known_names:
            return {"type": "material", "name": name, "count": count, "category": "monster"}
        if self._is_artifact_name(name):
            return {"type": "artifact", "count": count}
        # 其它材料（采集物等）：同样计入材料（名单还在完善，暂不区分怪物/普通）
        if not self.settings.get("enable_material", True):
            return None
        return {"type": "material", "name": name, "count": count, "category": "monster"}

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
        m = re.match(r"^([\u4e00-\u9fff]{1,8})\s*(?:[×xX]\s*(\d{1,3}))?\s*[×xX]?$", text)
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
