# -*- coding: utf-8 -*-
"""记账 + 识别日志 + 训练样本采集 —— 从 `detector._apply_event` 里抽出来（第 11 批）。

> 第 11 批 = `重构步骤细化.md` 的 **6.1（抽日志）+ 6.2（抽记账）**。

**为什么抽**：原来 `_apply_event` 一个方法里混着三件事 ——

```
① 判断"这一笔是不是新事件"（去重闸 tracker）   ← 这是**识别**
② 记到 stats 上、给界面拼一句「霜仙花 ×3」      ← 这是**记账**
③ 写识别日志、存训练样本                        ← 这是**事后可查的副作用**
```

①②③ 混在一起的结果：想换日志格式、想换个存储，都得动识别代码。
抽出之后 `detector` 只留 ①，②③ 全走这里。

⚠ **行为一个字没改。** 抽之前先有 `_morph\\test_detector_apply.py`
   （29 条断言）把现状钉死了，抽完再跑一遍必须一模一样。
"""
import time


class Accounting:
    """把一笔**已经确认**的收益记下来。

    - `stats`    ：`stats.DailyStats`。外部造好传进来；detector 仍然持有同一个对象。
    - `dataset`  ：`dataset_collector.DatasetCollector`（开发者选项，没开时它自己不干活）
    - `settings` ：设置字典，只用来透传给识别日志（日志里要记当时的开关状态）
    """

    def __init__(self, stats, dataset=None, settings=None):
        self.stats = stats
        self.dataset = dataset
        self.settings = settings if settings is not None else {}

    # ------------------------------------------------------------ 对外两个入口
    def record(self, ev, frame, source):
        """记一笔已确认的收益。

        返回 `(时间戳, 给界面看的一句话)` —— 调用方拿去塞 `det.last_event`。

        ⚠ 顺序跟抽之前**一模一样**：先写 stats → 再取时间戳 → 再存样本 → 最后写日志。
          （时间戳必须在样本/日志之前取，不然 `last_event` 的时间会偏。）
        ⚠ 样本采集和识别日志各自兜住异常 —— 它们炸了不能把记账带下水。
        """
        self._write_stats(ev)
        now = time.time()
        desc = self._describe(ev)
        self._capture_sample(ev, frame)
        self._write_log(ev, source)
        return (now, desc)

    def log_rejected(self, name, count, raw):
        """识别到但不在名单里的 —— 只写日志，不统计、不登记。

        这样翻日志能看出"哪些名字被丢掉了"，需要的话再手动加进名单。
        """
        self._log("未登记", name, count, 0, raw, "不在名单里")

    def log_dropped(self, kind, name, count, amount, raw, reason):
        """一笔**判定为误读、没有统计**的读数 —— 只写识别日志。

        典型场景：摩拉单次读数超过上限（多半是角色伤害数字跟摩拉叠在一起）。
        `log_rejected` 其实是它的特例（认出来了，但不在识别名单里）。

        `reason` 会写进日志的「来源」那一列，用「未统计（…）」开头，
        翻日志时一眼就能跟真正统计进去的条目区分开。
        """
        self._log(kind, name, count, amount, raw, reason)

    # ------------------------------------------------------------ 里面
    def _write_stats(self, ev):
        """真·记账。这一句**不兜异常**（跟抽之前一致：记不进去就该炸出来）。"""
        if ev["type"] == "mora":
            self.stats.add_mora(ev["amount"])
        elif ev["type"] == "material":
            self.stats.add_material(ev["name"], ev["count"],
                                    ev.get("category", "monster"))
        elif ev["type"] == "artifact":
            self.stats.add_artifact()

    @staticmethod
    def _describe(ev):
        """给界面看的那一句话（原来散在 `_apply_event` 三个分支里）"""
        if ev["type"] == "mora":
            return f"摩拉 +{ev['amount']}"
        if ev["type"] == "artifact":
            return "狗粮 +1"
        return f"{ev['name']} ×{ev['count']}"

    def _capture_sample(self, ev, frame):
        """开发者选项：确认拾取后，后台采集 GAMEPLAY 训练样本"""
        try:
            self.dataset.capture_gameplay(frame, str(ev.get("name", "")))
        except Exception:
            pass

    def _write_log(self, ev, source):
        """识别日志：记下这一笔 + 原始 OCR 文字，方便事后查错"""
        if ev["type"] == "mora":
            kind, nm, cnt, amt = "摩拉", "", 1, ev.get("amount", 0)
        elif ev["type"] == "artifact":
            kind, nm, cnt, amt = "狗粮", "", 1, 0
        else:
            kind, nm = "材料", ev.get("name", "")
            cnt, amt = ev.get("count", 1), 0
        self._log(kind, nm, cnt, amt, ev.get("raw", ""), source)

    def _log(self, kind, name, count, amount, raw, reason):
        """写一行识别日志。

        ⚠ `detect_log` 是**局部 import** —— 原来就是这样（它要去读 settings、
          可能还要开文件），保持懒加载，别把它提到模块顶层。
        """
        try:
            import detect_log
            detect_log.log_event(kind, name, count, amount, raw, reason,
                                 self.settings)
        except Exception:
            pass
