# -*- coding: utf-8 -*-
"""5行FIFO拾取Track生命周期测试（最终方案）

⚠ 第 12 批：Track 状态机从 `Detector` 搬到了 `track_manager.TrackManager`，
   `make_detector()` 里那一行是 `Detector.__init__` 那一步的镜像。
   `run_frames` 仍然是 `patch("detector.time.time")` —— 时钟留在 detector
   那边（`_observe_row_snapshot` 取好时间再喂给状态机），所以这个打桩照样有效。
"""
import unittest
from unittest.mock import patch

from detector import Detector
from track_manager import TrackManager


def make_detector():
    det = Detector.__new__(Detector)
    det._dbg = lambda: False
    det.accounted = []
    det._apply_event = lambda event, frame, score, use_tracker: det.accounted.append(event) or True
    det.tracks = TrackManager(
        absence_seconds=1.5,
        report=lambda ev, frame: det._apply_event(ev, frame, 0.0, use_tracker=False),
    )
    return det


def ev_mat(name="霜仙花", count=1):
    return {"type": "material", "name": name, "count": count, "category": "monster"}


def run_frames(det, frames, times):
    """用连续时间喂帧。times 是每帧对应的时间戳列表（单调递增）。"""
    results = []
    for obs, t in zip(frames, times):
        with patch("detector.time.time", return_value=t):
            results.append(det._observe_row_snapshot(obs, None))
    return results


class TestFifoRowTracks(unittest.TestCase):

    def test_same_row_continuous_frames_counts_once(self):
        det = make_detector()
        frames = [[ev_mat("霜仙花")]] * 10
        times = [0.1 * i for i in range(10)]
        results = run_frames(det, frames, times)
        self.assertEqual(results, [True] + [False] * 9)
        self.assertEqual(len(det.accounted), 1)

    def test_count_loss_does_not_break_track(self):
        det = make_detector()
        frames = [[ev_mat("霜仙花", 1)] for _ in range(4)]
        times = [0.1 * i for i in range(4)]
        run_frames(det, frames, times)
        self.assertEqual(len(det.accounted), 1)

    def test_rapid_same_item_counts_multiple(self):
        det = make_detector()
        frames = [
            [ev_mat("霜仙花")],
            [ev_mat("霜仙花"), ev_mat("霜仙花")],
            [ev_mat("霜仙花"), ev_mat("霜仙花"), ev_mat("霜仙花")],
            [ev_mat("霜仙花"), ev_mat("霜仙花"), ev_mat("霜仙花"), ev_mat("霜仙花")],
            [ev_mat("霜仙花"), ev_mat("霜仙花"), ev_mat("霜仙花"), ev_mat("霜仙花"), ev_mat("霜仙花")],
        ]
        times = [0.1 * i for i in range(5)]
        run_frames(det, frames, times)
        self.assertEqual(len(det.accounted), 5)

    def test_disappear_and_reappear_counts_again(self):
        det = make_detector()
        # t=0 出现 → +1；t=0.3 仍在；然后消失超过 absence，t=2.0 重现 → +1
        times = [0.0, 0.3, 2.0, 2.3]
        frames = [
            [ev_mat("霜仙花")],
            [ev_mat("霜仙花")],
            [],  # 空帧（可能漏读，但 t=2.0 已超 absence）
            [ev_mat("霜仙花")],
        ]
        results = run_frames(det, frames, times)
        # 第4帧重现应入账
        self.assertTrue(results[3])
        self.assertEqual(len(det.accounted), 2)

    def test_two_identical_frames_no_new(self):
        det = make_detector()
        times = [0.0, 0.1]
        frames = [[ev_mat("霜仙花")], [ev_mat("霜仙花")]]
        run_frames(det, frames, times)
        self.assertEqual(len(det.accounted), 1)

    def test_five_same_head_exit_new_enter(self):
        det = make_detector()
        times = [0.0, 0.3]
        frames = [
            [ev_mat("霜仙花")] * 5,
            [ev_mat("霜仙花")] * 5,
        ]
        run_frames(det, frames, times)
        # 两帧全同名且信息相同 → 按方案第8条：无法证明新事件，不新增
        self.assertEqual(len(det.accounted), 5)

    def test_distinct_items_in_queue(self):
        det = make_detector()
        times = [0.0, 0.1]
        frames = [
            [ev_mat("霜仙花"), ev_mat("甜甜花"), ev_mat("薄荷")],
            [ev_mat("霜仙花"), ev_mat("甜甜花"), ev_mat("薄荷")],
        ]
        run_frames(det, frames, times)
        self.assertEqual(len(det.accounted), 3)


if __name__ == "__main__":
    unittest.main()
