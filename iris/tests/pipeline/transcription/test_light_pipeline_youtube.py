"""Tests for the light pipeline YouTube path (no video file)."""

from unittest.mock import MagicMock

from iris.pipeline.transcription.light_pipeline import LightTranscriptionPipeline


class TestLightPipelineYouTubePath:
    """Verify the YouTube path produces Artemis-compatible segment format."""

    def _make_pipeline(self, segments):
        dto = MagicMock()
        dto.lecture_unit_id = 1
        callback = MagicMock()
        transcription = {"segments": segments}
        return LightTranscriptionPipeline(
            dto=dto,
            callback=callback,
            transcription=transcription,
            video_path=None,  # YouTube — no video file
        )

    def test_segments_use_artemis_key_names(self):
        """YouTube segments must use startTime/endTime, not start/end."""
        pipeline = self._make_pipeline([
            {"start": 0.0, "end": 5.0, "text": "Hello"},
            {"start": 5.0, "end": 10.0, "text": "World"},
        ])

        result = pipeline()

        assert len(result) == 2
        for seg in result:
            assert "startTime" in seg, "Missing 'startTime' — Artemis expects this key"
            assert "endTime" in seg, "Missing 'endTime' — Artemis expects this key"
            assert "start" not in seg, "Raw 'start' key must not leak to Artemis"
            assert "end" not in seg, "Raw 'end' key must not leak to Artemis"

    def test_segment_values_are_correct(self):
        pipeline = self._make_pipeline([
            {"start": 1.5, "end": 3.5, "text": "Content"},
        ])

        result = pipeline()

        seg = result[0]
        assert seg["startTime"] == 1.5
        assert seg["endTime"] == 3.5
        assert seg["text"] == "Content"
        assert seg["slideNumber"] == -1

    def test_all_segments_have_slide_number_minus_one(self):
        pipeline = self._make_pipeline([
            {"start": 0.0, "end": 5.0, "text": "A"},
            {"start": 5.0, "end": 10.0, "text": "B"},
            {"start": 10.0, "end": 15.0, "text": "C"},
        ])

        result = pipeline()

        assert all(seg["slideNumber"] == -1 for seg in result)

    def test_text_is_stripped(self):
        pipeline = self._make_pipeline([
            {"start": 0.0, "end": 5.0, "text": "  spaces  "},
        ])

        result = pipeline()

        assert result[0]["text"] == "spaces"

    def test_output_keys_match_artemis_dto(self):
        """Verify exact key set matches PyrisTranscriptionSegmentDTO."""
        pipeline = self._make_pipeline([
            {"start": 0.0, "end": 1.0, "text": "x"},
        ])

        result = pipeline()

        expected_keys = {"startTime", "endTime", "text", "slideNumber"}
        assert set(result[0].keys()) == expected_keys

    def test_empty_segments_returns_empty_list(self):
        pipeline = self._make_pipeline([])

        result = pipeline()

        assert result == []

    def test_callback_skip_called_twice(self):
        """Two stages (Detecting slides + Aligning) must be skipped."""
        pipeline = self._make_pipeline([
            {"start": 0.0, "end": 1.0, "text": "x"},
        ])

        pipeline()

        assert pipeline.callback.skip.call_count == 2

    def test_original_segments_not_mutated(self):
        """The input transcription dict must not be modified."""
        original_seg = {"start": 0.0, "end": 5.0, "text": "Hello"}
        segments = [original_seg]
        pipeline = self._make_pipeline(segments)

        pipeline()

        # Original segment should not have slideNumber added
        assert "slideNumber" not in original_seg
        # Original keys should be unchanged
        assert set(original_seg.keys()) == {"start", "end", "text"}
