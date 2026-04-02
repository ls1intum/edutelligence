"""Tests for transcript-to-slide alignment."""

from iris.pipeline.transcription.utils.alignment import align_slides_with_segments


class TestAlignSlidesWithSegments:
    def test_empty_segments(self):
        result = align_slides_with_segments([], [(0.0, 1)])
        assert result == []

    def test_empty_slide_timestamps(self):
        segments = [
            {"start": 0.0, "end": 5.0, "text": "Hello"},
            {"start": 5.0, "end": 10.0, "text": "World"},
        ]
        result = align_slides_with_segments(segments, [])
        assert len(result) == 2
        assert all(seg["slideNumber"] == -1 for seg in result)

    def test_both_empty(self):
        result = align_slides_with_segments([], [])
        assert result == []

    def test_single_slide_all_segments_match(self):
        segments = [
            {"start": 0.0, "end": 5.0, "text": "Intro"},
            {"start": 5.0, "end": 10.0, "text": "Content"},
            {"start": 10.0, "end": 15.0, "text": "More"},
        ]
        result = align_slides_with_segments(segments, [(0.0, 1)])
        assert len(result) == 3
        assert all(seg["slideNumber"] == 1 for seg in result)

    def test_multiple_slide_changes(self):
        segments = [
            {"start": 0.0, "end": 10.0, "text": "Slide one"},
            {"start": 10.0, "end": 20.0, "text": "Slide two"},
            {"start": 25.0, "end": 30.0, "text": "Still slide two"},
            {"start": 30.0, "end": 40.0, "text": "Slide three"},
        ]
        slide_timestamps = [(0.0, 1), (10.0, 2), (30.0, 3)]
        result = align_slides_with_segments(segments, slide_timestamps)

        assert result[0]["slideNumber"] == 1
        assert result[1]["slideNumber"] == 2
        assert result[2]["slideNumber"] == 2
        assert result[3]["slideNumber"] == 3

    def test_segment_before_first_slide_change(self):
        segments = [
            {"start": 0.0, "end": 5.0, "text": "Before any slide"},
            {"start": 10.0, "end": 15.0, "text": "After first slide"},
        ]
        slide_timestamps = [(5.0, 1)]
        result = align_slides_with_segments(segments, slide_timestamps)

        assert result[0]["slideNumber"] == -1  # Before any slide change
        assert result[1]["slideNumber"] == 1

    def test_output_format(self):
        segments = [{"start": 1.5, "end": 3.5, "text": "  Hello  "}]
        result = align_slides_with_segments(segments, [(0.0, 1)])

        assert len(result) == 1
        seg = result[0]
        assert seg["startTime"] == 1.5
        assert seg["endTime"] == 3.5
        assert seg["text"] == "Hello"  # Stripped
        assert seg["slideNumber"] == 1
        assert set(seg.keys()) == {"startTime", "endTime", "text", "slideNumber"}

    def test_unsorted_slide_timestamps_are_sorted(self):
        segments = [
            {"start": 0.0, "end": 5.0, "text": "A"},
            {"start": 15.0, "end": 20.0, "text": "B"},
        ]
        # Deliberately unsorted
        slide_timestamps = [(10.0, 2), (0.0, 1)]
        result = align_slides_with_segments(segments, slide_timestamps)

        assert result[0]["slideNumber"] == 1
        assert result[1]["slideNumber"] == 2

    def test_slide_change_at_exact_segment_start(self):
        segments = [{"start": 5.0, "end": 10.0, "text": "Content"}]
        slide_timestamps = [(5.0, 3)]
        result = align_slides_with_segments(segments, slide_timestamps)

        # Slide change at exactly segment start time should match (ts <= start)
        assert result[0]["slideNumber"] == 3
