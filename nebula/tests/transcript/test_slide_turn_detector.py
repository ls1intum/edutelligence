# pylint: disable=protected-access
from collections import OrderedDict
from unittest.mock import MagicMock, patch

import nebula.transcript.slide_turn_detector as std
import nebula.transcript.slide_utils as slide_utils


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
    def fake_frame_cache_init(
        self, video_path, segs, capture_offset_ratio=0.2, capacity=16
    ):
        self.video_path = video_path
        self.segments = segs
        self.capture_offset_ratio = capture_offset_ratio
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


def _stub_frame_cache(monkeypatch):
    """Helper to stub out frame cache for all tests."""

    def fake_frame_cache_init(
        self, video_path, segs, capture_offset_ratio=0.2, capacity=16
    ):
        self.video_path = video_path
        self.segments = segs
        self.capture_offset_ratio = capture_offset_ratio
        self.capacity = capacity
        self.fps = 30.0
        self._cache = OrderedDict()

    monkeypatch.setattr(std._FrameCache, "__init__", fake_frame_cache_init)
    monkeypatch.setattr(std._FrameCache, "get", lambda self, idx: "fake_frame_b64")
    monkeypatch.setattr(std._FrameCache, "close", lambda self: None)


class TestGptResponseHandling:
    """Tests that verify GPT responses are correctly translated to slide labels."""

    def test_gpt_null_response_returns_negative_one(self):
        """When GPT says 'null' (no slide visible), should return -1."""
        # Mock GPT to return "null"
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "null"

        with patch.object(slide_utils, "get_openai_client") as mock_client:
            mock_client.return_value = (MagicMock(), "gpt-4.1-mini")
            mock_client.return_value[0].chat.completions.create.return_value = (
                mock_response
            )

            result = slide_utils.ask_gpt_for_slide_number("fake_b64")

        assert result == -1

    def test_gpt_unknown_response_returns_negative_one(self):
        """When GPT says 'unknown', should return -1."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "unknown"

        with patch.object(slide_utils, "get_openai_client") as mock_client:
            mock_client.return_value = (MagicMock(), "gpt-4.1-mini")
            mock_client.return_value[0].chat.completions.create.return_value = (
                mock_response
            )

            result = slide_utils.ask_gpt_for_slide_number("fake_b64")

        assert result == -1

    def test_gpt_slide_number_response_returns_integer(self):
        """When GPT returns a slide number, should return that integer."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "5"

        with patch.object(slide_utils, "get_openai_client") as mock_client:
            mock_client.return_value = (MagicMock(), "gpt-4.1-mini")
            mock_client.return_value[0].chat.completions.create.return_value = (
                mock_response
            )

            result = slide_utils.ask_gpt_for_slide_number("fake_b64")

        assert result == 5


class TestSlideDetectionScenarios:
    """Integration tests for various slide detection scenarios with mocked GPT."""

    def test_no_slides_at_start_then_slides_appear(self, monkeypatch):
        """Scenario: Video starts with no slides, then slides appear."""
        segments = [
            {"start": float(i), "end": float(i + 1), "text": f"seg{i}"}
            for i in range(6)
        ]
        _stub_frame_cache(monkeypatch)

        # Segments 0-2: no slide (-1), Segments 3-5: slide 1
        label_map = {0: -1, 1: -1, 2: -1, 3: 1, 4: 1, 5: 1}

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

        assert change_points == [(0.0, -1), (3.0, 1)]

    def test_slides_then_no_slides_at_end(self, monkeypatch):
        """Scenario: Video has slides at start, then no slides at end."""
        segments = [
            {"start": float(i), "end": float(i + 1), "text": f"seg{i}"}
            for i in range(6)
        ]
        _stub_frame_cache(monkeypatch)

        # Segments 0-2: slide 1, Segments 3-5: no slide (-1)
        label_map = {0: 1, 1: 1, 2: 1, 3: -1, 4: -1, 5: -1}

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

        assert change_points == [(0.0, 1), (3.0, -1)]

    def test_all_no_slides(self, monkeypatch):
        """Scenario: Entire video has no slides."""
        segments = [
            {"start": float(i), "end": float(i + 1), "text": f"seg{i}"}
            for i in range(5)
        ]
        _stub_frame_cache(monkeypatch)

        # All segments return -1 (no slide)
        monkeypatch.setattr(std.SlideTurnDetector, "_query_label", lambda self, idx: -1)

        change_points = std.detect_slide_timestamps(
            video_path="dummy",
            segments=segments,
            anchor_stride=2,
            min_stride=1,
            job_id=None,
        )

        assert change_points == [(0.0, -1)]

    def test_alternating_slides_and_no_slides(self, monkeypatch):
        """Scenario: Video alternates between slides and no-slide sequences."""
        segments = [
            {"start": float(i), "end": float(i + 1), "text": f"seg{i}"}
            for i in range(9)
        ]
        _stub_frame_cache(monkeypatch)

        # 0-2: slide 1, 3-5: no slide, 6-8: slide 2
        label_map = {0: 1, 1: 1, 2: 1, 3: -1, 4: -1, 5: -1, 6: 2, 7: 2, 8: 2}

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

        assert change_points == [(0.0, 1), (3.0, -1), (6.0, 2)]

    def test_single_no_slide_segment_in_middle(self, monkeypatch):
        """Scenario: Single no-slide segment between slides."""
        segments = [
            {"start": float(i), "end": float(i + 1), "text": f"seg{i}"}
            for i in range(5)
        ]
        _stub_frame_cache(monkeypatch)

        # 0-1: slide 1, 2: no slide, 3-4: slide 2
        label_map = {0: 1, 1: 1, 2: -1, 3: 2, 4: 2}

        monkeypatch.setattr(
            std.SlideTurnDetector, "_query_label", lambda self, idx: label_map[idx]
        )

        change_points = std.detect_slide_timestamps(
            video_path="dummy",
            segments=segments,
            anchor_stride=2,
            min_stride=1,
            job_id=None,
        )

        assert change_points == [(0.0, 1), (2.0, -1), (3.0, 2)]

    def test_gpt_error_falls_back_to_previous_label(self, monkeypatch):
        """Scenario: GPT fails (returns None) - should carry forward last label."""
        segments = [
            {"start": float(i), "end": float(i + 1), "text": f"seg{i}"}
            for i in range(4)
        ]
        _stub_frame_cache(monkeypatch)

        # 0: slide 1, 1: GPT error (None), 2: GPT error (None), 3: slide 1
        label_map = {0: 1, 1: None, 2: None, 3: 1}

        monkeypatch.setattr(
            std.SlideTurnDetector, "_query_label", lambda self, idx: label_map[idx]
        )

        change_points = std.detect_slide_timestamps(
            video_path="dummy",
            segments=segments,
            anchor_stride=2,
            min_stride=1,
            job_id=None,
        )

        # None segments get filled with last known label (1), so all are slide 1
        assert change_points == [(0.0, 1)]

    def test_gpt_error_at_start_defaults_to_negative_one(self, monkeypatch):
        """Scenario: GPT fails at start (before any slide seen) - defaults to -1."""
        segments = [
            {"start": float(i), "end": float(i + 1), "text": f"seg{i}"}
            for i in range(4)
        ]
        _stub_frame_cache(monkeypatch)

        # 0: GPT error (None), 1: GPT error (None), 2: slide 1, 3: slide 1
        label_map = {0: None, 1: None, 2: 1, 3: 1}

        monkeypatch.setattr(
            std.SlideTurnDetector, "_query_label", lambda self, idx: label_map[idx]
        )

        change_points = std.detect_slide_timestamps(
            video_path="dummy",
            segments=segments,
            anchor_stride=2,
            min_stride=1,
            job_id=None,
        )

        # None at start defaults to -1, then changes to slide 1
        assert change_points == [(0.0, -1), (2.0, 1)]
