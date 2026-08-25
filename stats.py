# -*- coding: utf-8 -*-
"""
每日统计模块

数据文件：
- data/today.json   今日收益（程序每次保存）
- data/history.json 历史数据（换日时自动归档）

关键设计：
- 启动时检查日期，如果今天已经换了，自动把昨天的数据存进历史
- 昨天、今天的数据完全分开
- 提供"清空今日收益"功能（历史数据不受影响）
"""
import json
import time
from datetime import date
from pathlib import Path
import paths

BASE_DIR = paths.app_dir()
DATA_DIR = BASE_DIR / "data"
TODAY_FILE = DATA_DIR / "today.json"
HISTORY_FILE = DATA_DIR / "history.json"


class DailyStats:
    """今日收益数据"""

    def __init__(self, base_dir=None):
        if base_dir is not None:
            self.data_dir = Path(base_dir)
        else:
            self.data_dir = DATA_DIR
        self.today_file = self.data_dir / "today.json"
        self.history_file = self.data_dir / "history.json"

        self.date = ""
        self.mora = 0
        self.materials = {}        # 怪物掉落物 {"材料名称": 数量}
        self.normal_materials = {} # 普通材料（采集物等）{"材料名称": 数量}
        self.artifact = 0          # 狗粮数量
        self.running_seconds = 0
        self._load()

    # ---------- 加载 / 保存 ----------

    def _load(self):
        today = date.today().isoformat()
        if self.today_file.exists():
            try:
                data = json.loads(self.today_file.read_text(encoding="utf-8"))
                if data.get("date") == today:
                    # 还是今天，直接恢复
                    self.date = today
                    self.mora = data.get("mora", 0)
                    self.materials = data.get("materials", {})
                    self.normal_materials = data.get("normal_materials", {})
                    self.artifact = data.get("artifact", 0)
                    self.running_seconds = data.get("running_seconds", 0)
                    return
                else:
                    # 是昨天的数据，先归档再开新的一天
                    self._archive(data)
            except Exception:
                pass  # 文件损坏就当新的一天
        self.date = today
        self.save()

    def _archive(self, old_data):
        """把旧一天的数据存进历史"""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        history = {}
        if self.history_file.exists():
            try:
                history = json.loads(self.history_file.read_text(encoding="utf-8"))
            except Exception:
                history = {}
        history[old_data.get("date", "unknown")] = old_data
        self.history_file.write_text(
            json.dumps(history, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def save(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.today_file.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def to_dict(self):
        return {
            "date": self.date,
            "mora": self.mora,
            "materials": self.materials,
            "normal_materials": self.normal_materials,
            "artifact": self.artifact,
            "running_seconds": self.running_seconds,
        }

    # ---------- 统计操作 ----------

    def add_mora(self, amount):
        self.mora += amount
        self.save()

    def add_material(self, name, count, category="monster"):
        """category: 'monster'=怪物掉落物, 'normal'=普通材料"""
        if category == "normal":
            self.normal_materials[name] = self.normal_materials.get(name, 0) + count
        else:
            self.materials[name] = self.materials.get(name, 0) + count
        self.save()

    def add_artifact(self):
        self.artifact += 1
        self.save()

    def clear_today(self):
        """清空今日收益（历史数据不动，挂机时间保留）"""
        self.mora = 0
        self.materials = {}
        self.normal_materials = {}
        self.artifact = 0
        self.save()

    def clear_running_seconds(self):
        """单独清空挂机时间（收益数据不动）"""
        self.running_seconds = 0
        self.save()


class EventTracker:
    """
    奖励事件去重器（整个软件最重要的部分）

    原理：每种奖励记住"上次看到的时间"。
    - 提示一直显示：时间不断刷新 → 不会重复统计
    - 提示消失超过 end_window 秒：再出现就是新事件 → 统计一次

    这样就保证了：
    破损的面具 ×1 连续显示 100 帧 → 只统计 1 次
    消失后再出现 ×1 → 正确统计成 +1
    """

    def __init__(self, end_window=1.5):
        self.end_window = end_window
        self.last_seen = {}  # 事件键 -> 上次看到的时间戳

    def is_new_event(self, key, now=None):
        """
        判断某个奖励是否是新事件（应该统计）
        是 → 返回 True，并记录当前时间
        否 → 返回 False（提示还在显示，不重复统计）
        """
        now = now if now is not None else time.time()
        last = self.last_seen.get(key, 0.0)
        self.last_seen[key] = now
        return (now - last) > self.end_window
