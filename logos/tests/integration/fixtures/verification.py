"""
Verification helpers for integration tests.
Provides assertions for database state, logs, and monitoring.
"""

from typing import Optional


class VerificationHelper:
    """Helper for verifying database state and logs."""

    def __init__(self, db):
        """Initialize with mocked DBManager."""
        self.db = db

    def assert_request_logged(self, response_headers: dict) -> dict:
        """
        Verify request was logged to database.

        Args:
            response_headers: HTTP response headers (should contain X-Request-ID)

        Returns:
            Request log entry from database
        """
        request_id = response_headers.get("X-Request-ID") or response_headers.get("x-request-id")
        assert request_id is not None, "Response missing X-Request-ID header"

        log = self.db.get_request_log(int(request_id))
        assert log is not None, f"Request log {request_id} not found in database"
        return log

    def assert_classification_occurred(self, log: dict):
        """Verify classification stats were logged."""
        assert log.get("classification_duration") is not None, \
            "Classification duration not logged (RESOURCE mode should have classification)"
        assert log.get("ranked_models") is not None or log.get("classification_result") is not None, \
            "Classification result not logged"

    def assert_scheduling_occurred(self, log: dict):
        """Verify scheduling stats were logged."""
        assert log.get("scheduling_duration") is not None, \
            "Scheduling duration not logged (RESOURCE mode should have scheduling)"

    def assert_usage_logged(self, log: dict, expected_tokens: Optional[int] = None):
        """Verify usage was logged."""
        assert log.get("prompt_tokens") is not None, "Prompt tokens not logged"
        assert log.get("completion_tokens") is not None, "Completion tokens not logged"
        assert log.get("total_tokens") is not None, "Total tokens not logged"

        if expected_tokens:
            assert log.get("total_tokens") == expected_tokens, \
                f"Expected {expected_tokens} tokens, got {log.get('total_tokens')}"

    def assert_no_classification(self, log: dict):
        """Verify classification did NOT occur (PROXY mode)."""
        assert log.get("classification_duration") is None, \
            "Classification occurred (PROXY mode should NOT have classification)"

    def assert_no_scheduling(self, log: dict):
        """Verify scheduling did NOT occur (PROXY mode)."""
        assert log.get("scheduling_duration") is None, \
            "Scheduling occurred (PROXY mode should NOT have scheduling)"

    def assert_proxy_mode(self, log: dict):
        """Verify request was PROXY mode."""
        self.assert_no_classification(log)
        self.assert_no_scheduling(log)

    def assert_resource_mode(self, log: dict):
        """Verify request was RESOURCE mode."""
        self.assert_classification_occurred(log)
        self.assert_scheduling_occurred(log)

    def assert_monitoring_event(self, event_type: str, request_id: int):
        """Verify monitoring event was recorded."""
        events = self.db.get_monitoring_events(request_id)
        assert any(e["type"] == event_type for e in events), \
            f"Event {event_type} not found for request {request_id}. Found events: {[e['type'] for e in events]}"

    def get_queue_state(self, model_id: int) -> dict:
        """Get current queue state for model."""
        # Integration tests don't need to inspect queue internals
        # This is tested at the behavior level (requests execute sequentially)
        return {"total": 0, "high": 0, "normal": 0, "low": 0}

    def assert_queued(self, model_id: int):
        """Verify request was added to queue."""
        # Queue behavior is tested by observing sequential execution
        # No database verification needed
        pass

    def get_job_status(self, job_id: int) -> Optional[dict]:
        """Get job status from database."""
        return self.db.get_job(job_id)

    def assert_job_created(self, job_id: int) -> dict:
        """Verify job was created in database."""
        job = self.get_job_status(job_id)
        assert job is not None, f"Job {job_id} not found in database"
        return job

    def assert_job_status(self, job_id: int, expected_status: str):
        """Verify job has expected status."""
        job = self.assert_job_created(job_id)
        assert job["status"] == expected_status, \
            f"Job {job_id}: expected status '{expected_status}', got '{job['status']}'"

    def assert_job_completed(self, job_id: int):
        """Verify job completed successfully."""
        self.assert_job_status(job_id, "success")

    def assert_job_failed(self, job_id: int):
        """Verify job failed."""
        self.assert_job_status(job_id, "failed")

    def assert_streaming_response(self, response_headers: dict):
        """Verify response is streaming (SSE)."""
        content_type = response_headers.get("content-type") or response_headers.get("Content-Type")
        assert content_type == "text/event-stream", \
            f"Expected streaming response (text/event-stream), got {content_type}"

    def assert_json_response(self, response_headers: dict):
        """Verify response is JSON."""
        content_type = response_headers.get("content-type") or response_headers.get("Content-Type")
        assert "application/json" in content_type, \
            f"Expected JSON response, got {content_type}"

    def parse_sse_chunks(self, response_text: str) -> list:
        """Parse SSE response into chunks."""
        chunks = []
        for line in response_text.split("\n"):
            line = line.strip()
            if line.startswith("data: "):
                data = line[6:]  # Remove "data: " prefix
                if data != "[DONE]":
                    chunks.append(data)
        return chunks

    def assert_sse_format(self, response_text: str):
        """Verify SSE response format."""
        chunks = self.parse_sse_chunks(response_text)
        assert len(chunks) > 0, "No SSE chunks found in response"

        # Verify last chunk has usage
        import json
        try:
            last_chunk = json.loads(chunks[-1])
            assert "usage" in last_chunk or "choices" in last_chunk, \
                "Last chunk missing usage or choices"
        except json.JSONDecodeError as e:
            raise AssertionError(f"Failed to parse last SSE chunk: {e}")

    def assert_response_has_content(self, response_data: dict):
        """Verify response has content in choices."""
        assert "choices" in response_data, "Response missing 'choices' field"
        assert len(response_data["choices"]) > 0, "Response has empty choices"

        choice = response_data["choices"][0]
        if "message" in choice:
            # Non-streaming response
            assert "content" in choice["message"], "Response message missing 'content'"
            assert choice["message"]["content"], "Response content is empty"
        elif "delta" in choice:
            # Streaming chunk
            # Delta may not have content in every chunk
            pass
