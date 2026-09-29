# -*- coding: utf-8 -*-
"""5 行 FIFO 拾取 Track 的生命周期状态机 —— 从 `detector` 里抽出来（第 12 批）。

> 第 12 批 = `重构步骤细化.md` 的 **6.3（抽 Track 生命周期）**，
>   也是「第 6 步 detector 分层」的最后一步（6.4 解析核心原地不动）。

**为什么抽**：`detector` 一个类同时管着截屏、主界面判定、OCR 解析、
Track 状态机、记账。其中 Track 这一块是**唯一带真状态**的
（`VISIBLE / MISSING / ENDED` + 队列顺序 + counted 标志），
跟识别管线其它部分混在一起，改它要在 1000 行的文件里翻。

**抽法**（跟第 9~11 批一样：**先有尺子，再搬**）：

```
_morph\\test_detector_tracks.py   10 个场景 / 14 条【必过】断言   ← 主尺子
test_event_lifecycle.py           7 个 unittest（仓库根目录，用户也在跑）
_morph\\test_counting.py          防多记 / 防漏记
```

三个一起跑，行为一个字节都不许变。

⚠ **时钟由调用方传进来**（`observe(observations, frame, now)`），这个类
  自己不 import time。两个理由：
    ① 状态机变成纯函数式的了，喂个时间戳就能测；
    ② 现有测试是 `patch("detector.time.time")` 打的桩 ——
       时钟留在 detector 那边，它们才继续有效。
"""


class TrackManager:
    """把左下角「获得」列表建模成**最多 5 行的有序 FIFO 队列**。

    铁律（文档第 3~17 章，别再忘）：

    ```
    [A, B, C, D, E]     满了
    新事件 F 从队尾进入、A 出队
    [B, C, D, E, F]
    ```

    · **Track ≠ 物品名称** —— `霜仙花` 连捡 3 次是 **3 个独立 Track**
    · **严禁用 Y 坐标做身份** —— 下方提示会平滑补位，`Y 变了 ≠ Track 变了`
    · 身份 = 有序队列连续性 + identity + 生命周期
      （**LCS 只用来找"保留关系"**，不能直接决定"这行是不是新事件"）
    · **MISSING ≠ ENDED** —— 单帧没 OCR 到只是 MISSING，超时才 ENDED
    · **每个 Track 只入账一次**
      （`counted=False → report() → counted=True`，之后看 100 帧也不再记）
    · 不等两帧、**立即统计** —— 新 Track 可靠识别后马上入账
    """

    def __init__(self, absence_seconds=1.5, report=None):
        """
        absence_seconds：多久没再看到就算 ENDED（原 `event_end_window`）
        report         ：新事件回调 `report(ev, frame) -> bool`
                         （detector 传进来的是"入账"那一下）
        """
        self.absence_seconds = float(absence_seconds)
        self._report = report if report is not None else (lambda ev, frame: False)
        self._tracks = {}      # track id -> 单行生命周期
        self._order = []       # 上一次 OCR 中行实例的从上到下顺序
        self._next_id = 1

    # ------------------------------------------------------------ 只读视图
    # （测试和排查用；改它们没有意义 —— 真正的状态只有 observe() 会动）
    @property
    def tracks(self):
        return self._tracks

    @property
    def order(self):
        return list(self._order)

    # ------------------------------------------------------------ 主入口
    def observe(self, observations, frame, now):
        """喂一帧 OCR 结果，返回**是否统计到了新收益**。

        - 拾取提示建模为最多 5 行的有序 FIFO 队列。
        - Track 身份 = 有序队列连续 + identity，不用 Y 坐标（补位会变）。
        - 用"最大有序重叠"（LCS）匹配旧 Track 与当前行，保留原有 Track。
        - 只有"队尾新增"的行才创建新 Track 并入账一次。
        - 两帧完全相同、无可证明的新事件时，不新增不统计。
        - counted 的 Track 生命周期内只入账一次。
        - OCR 短暂漏读进入 MISSING，不等于结束。

        ⚠ `now` 由调用方取（`detector` 那边 `time.time()`），
          这样 `patch("detector.time.time")` 那种打桩才管用。
        """
        if not observations:
            # 没有观察到任何行：把未超时的 Track 标记为 MISSING（不立即 END）
            for tid in list(self._tracks):
                st = self._tracks[tid]
                if st["state"] != "ended":
                    if now - st["last_seen"] > self.absence_seconds:
                        st["state"] = "ended"
                    else:
                        st["state"] = "missing"
            self._prune(now)
            return False

        # 1. 活跃 Track（未 ended、且在 absence 窗口内）
        active_ids = [tid for tid in self._order
                      if tid in self._tracks
                      and self._tracks[tid].get("state") != "ended"
                      and now - self._tracks[tid]["last_seen"] <= self.absence_seconds]
        old_labels = [self._tracks[tid]["label"] for tid in active_ids]
        new_labels = [self.row_label(ev) for ev in observations]

        # 2. 最大有序重叠（LCS）：保留原有 Track，识别队尾新增
        pairs = self.lcs_pairs(old_labels, new_labels)
        matched_new = {new_i: active_ids[old_i] for old_i, new_i in pairs}

        current_ids = []
        added = False
        for index, ev in enumerate(observations):
            label = new_labels[index]
            track_id = matched_new.get(index)
            if track_id is None:
                # 队尾新增 → 新 Track，可靠识别后立即入账一次
                track_id = self._next_id
                self._next_id += 1
                self._tracks[track_id] = {
                    "label": label,
                    "identity": self.event_identity(ev),
                    "event": ev,
                    "first_seen": now,
                    "last_seen": now,
                    "state": "visible",
                    "counted": False,
                }
                # 新 Track 入账一次，之后不再重复
                self._tracks[track_id]["counted"] = True
                added = self._report(ev, frame) or added
            else:
                # 复用旧 Track（同一行提示的连续帧）
                st = self._tracks[track_id]
                st["last_seen"] = now
                st["state"] = "visible"
                st["event"] = ev  # 更新最新读数
            current_ids.append(track_id)

        self._order = current_ids
        self._prune(now)
        return added

    # ------------------------------------------------------------ 内部
    def _prune(self, now):
        """回收 ended 或超时的 Track，避免内存增长"""
        for tid in list(self._tracks):
            st = self._tracks[tid]
            if now - st["last_seen"] > self.absence_seconds:
                st["state"] = "ended"
            if now - st["last_seen"] > 15.0:
                del self._tracks[tid]

    @staticmethod
    def row_label(ev):
        """行匹配只看收益类别和名称；数量属于同一行的 OCR 读数。"""
        if ev["type"] == "mora":
            return "mora"
        if ev["type"] == "artifact":
            return "artifact"
        return "material:" + ev["name"]

    @staticmethod
    def event_identity(ev):
        """同一条提示在 OCR 中数量/符号波动时，仍归为同一个事件。"""
        if ev["type"] == "mora":
            return "mora"
        if ev["type"] == "artifact":
            return "artifact"
        return "material:" + ev["name"]

    @staticmethod
    def lcs_pairs(old_labels, new_labels):
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
