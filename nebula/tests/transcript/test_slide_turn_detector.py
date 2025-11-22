# pylint: disable=protected-access
from collections import OrderedDict

import nebula.transcript.slide_turn_detector as std


def test_detect_slide_timestamps_resolves_changes(monkeypatch):
    segments = [
        {"start": float(i), "end": float(i + 1), "text": f"seg{i}"} for i in range(10)
    ]
    # Ground truth labels: 0-2 => 1, 3-5 => 2, 6-9 => -1
    label_map = {
        0: 1,
        1: 1,
        2: 1,
        3: 2,
        4: 2,
        5: 2,
        6: -1,
        7: -1,
        8: -1,
        9: -1,
    }

    # Avoid real video I/O: stub frame cache to no-op.
    def fake_frame_cache_init(self, video_path, segs, capacity=16):
        self.video_path = video_path
        self.segments = segs
        self.capacity = capacity
        self.fps = 30.0
        self._cache = OrderedDict()

    monkeypatch.setattr(std._FrameCache, "__init__", fake_frame_cache_init)
    monkeypatch.setattr(std._FrameCache, "get", lambda self, idx: "frame")
    monkeypatch.setattr(std._FrameCache, "close", lambda self: None)

    # Drive labels directly without GPT.
    monkeypatch.setattr(
        std.SlideTurnDetector, "_query_label", lambda self, idx: label_map[idx]
    )

    change_points = std.detect_slide_timestamps(
        video_path="dummy",
        segments=segments,
        anchor_stride=3,
        min_stride=1,
        job_id=None,
    )

    assert change_points == [(0.0, 1), (3.0, 2), (6.0, -1)]
