class WatermarkTracker:
    """Track event-time progress while excluding inputs that became idle."""

    def __init__(self, input_count: int, idle_timeout_ms: int):
        self._watermarks = {input_id: -1 for input_id in range(input_count)}
        self._last_activity = {input_id: 0 for input_id in range(input_count)}
        self._idle_timeout_ms = idle_timeout_ms

    def observe_record(self, input_id: int, processing_time_ms: int) -> None:
        self._last_activity[input_id] = processing_time_ms

    def observe_watermark(
        self, input_id: int, watermark_ms: int, processing_time_ms: int
    ) -> None:
        self._watermarks[input_id] = max(self._watermarks[input_id], watermark_ms)
        self._last_activity[input_id] = processing_time_ms

    def current(self, processing_time_ms: int) -> int:
        active = [
            self._watermarks[input_id]
            for input_id, last_seen in self._last_activity.items()
            if processing_time_ms - last_seen < self._idle_timeout_ms
        ]
        return min(active) if active else max(self._watermarks.values())
