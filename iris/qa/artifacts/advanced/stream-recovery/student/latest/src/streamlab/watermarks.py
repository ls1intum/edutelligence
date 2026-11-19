class WatermarkTracker:
    """Track the minimum event-time watermark across inputs."""

    def __init__(self, input_count: int, idle_timeout_ms: int):
        self._watermarks = {input_id: -1 for input_id in range(input_count)}
        self._idle_timeout_ms = idle_timeout_ms

    def observe_record(self, input_id: int, processing_time_ms: int) -> None:
        del input_id, processing_time_ms
        return None

    def observe_watermark(
        self, input_id: int, watermark_ms: int, processing_time_ms: int
    ) -> None:
        del processing_time_ms
        self._watermarks[input_id] = max(self._watermarks[input_id], watermark_ms)

    def current(self, processing_time_ms: int) -> int:
        del processing_time_ms
        return min(self._watermarks.values())
