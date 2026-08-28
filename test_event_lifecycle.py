# -*- coding: utf-8 -*-
"""不需要游戏画面的核心防重复测试。"""
import unittest
from unittest.mock import patch

from detector import Detector


class EventLifecycleTests(unittest.TestCase):
    def make_detector(self):
        detector = Detector.__new__(Detector)
        detector._lifecycles = {}
        detector._confirm_seconds = 0.60
        detector._absence_seconds = 1.50
        detector._row_tracks = {}
        detector._last_row_order = []
        detector._next_row_track_id = 1
        detector._dbg = lambda: False
        detector._apply_event = lambda event, frame, score, use_tracker: recorded.append(event.copy()) or True
        return detector

    def test_one_visible_prompt_is_recorded_once_despite_ocr_variation(self):
        global recorded
        recorded = []
        detector = self.make_detector()
        # OCR 从缺失数量、读成 1，到稳定读成 3：仍是同一个提示生命周期。
        readings = [
            {"type": "material", "name": "破损的面具", "count": 1},
            {"type": "material", "name": "破损的面具", "count": 3},
            {"type": "material", "name": "破损的面具", "count": 3},
            {"type": "material", "name": "破损的面具", "count": 3},
        ]
        with patch("detector.time.time", side_effect=[0.0, 0.30, 0.61, 1.00]):
            results = [detector._observe_event(event, None) for event in readings]
        self.assertEqual(results, [False, False, True, False])
        self.assertEqual(recorded, [{"type": "material", "name": "破损的面具", "count": 3}])

    def test_same_item_can_be_recorded_again_only_after_real_absence(self):
        global recorded
        recorded = []
        detector = self.make_detector()
        event = {"type": "material", "name": "破损的面具", "count": 1}
        with patch("detector.time.time", side_effect=[0.0, 0.61, 1.00, 3.00, 3.61]):
            results = [detector._observe_event(event, None) for _ in range(5)]
        self.assertEqual(results, [False, True, False, False, True])
        self.assertEqual(len(recorded), 2)

    def test_five_same_material_rows_are_five_independent_events(self):
        global recorded
        recorded = []
        detector = self.make_detector()
        rows = [{"type": "material", "name": "破损的面具", "count": 1} for _ in range(5)]
        with patch("detector.time.time", side_effect=[0.0, 0.30, 0.61, 1.00]):
            for _ in range(4):
                detector._observe_row_snapshot(rows, None)
        self.assertEqual(len(recorded), 5)

    def test_new_same_material_row_at_bottom_is_not_merged(self):
        global recorded
        recorded = []
        detector = self.make_detector()
        event = {"type": "material", "name": "破损的面具", "count": 1}
        with patch("detector.time.time", side_effect=[0.0, 0.61, 1.00, 1.61]):
            detector._observe_row_snapshot([event], None)
            detector._observe_row_snapshot([event], None)
            detector._observe_row_snapshot([event, event], None)
            detector._observe_row_snapshot([event, event], None)
        self.assertEqual(len(recorded), 2)


if __name__ == "__main__":
    unittest.main()
