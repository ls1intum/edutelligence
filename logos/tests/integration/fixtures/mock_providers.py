"""
Mock provider endpoints with realistic responses.
Supports Azure and OpenWebUI with streaming and non-streaming responses.
"""

import json
from pathlib import Path
from typing import Dict, Optional
from httpx import Response


class ProviderMocker:
    """Mock provider endpoints with realistic responses."""

    def __init__(self, respx_mock):
        self.respx_mock = respx_mock
        self._routes = {}
        self._data_dir = Path(__file__).parent.parent / "data" / "responses"

    def mock_azure_streaming(
        self,
        base_url: str,
        deployment_name: str,
        model: str = "gpt-4",
        status_code: int = 200
    ):
        """Mock Azure streaming response."""
        url_pattern = f"{base_url}/{deployment_name}/chat/completions*"

        route = self.respx_mock.post(url__regex=url_pattern.replace("*", ".*")).mock(
            return_value=Response(
                status_code=status_code,
                headers={
                    "content-type": "text/event-stream",
                    "x-ms-region": "eastus",
                    "x-ratelimit-remaining-requests": "100",
                    "x-ratelimit-remaining-tokens": "50000"
                },
                content=self._load_streaming_response("azure_streaming.txt", model)
            )
        )
        route_name = f"azure_{deployment_name}_streaming"
        self._routes[route_name] = route
        return route

    def mock_azure_sync(
        self,
        base_url: str,
        deployment_name: str,
        model: str = "gpt-4",
        status_code: int = 200
    ):
        """Mock Azure non-streaming response."""
        url_pattern = f"{base_url}/{deployment_name}/chat/completions*"

        route = self.respx_mock.post(url__regex=url_pattern.replace("*", ".*")).mock(
            return_value=Response(
                status_code=status_code,
                headers={
                    "content-type": "application/json",
                    "x-ms-region": "eastus",
                    "x-ratelimit-remaining-requests": "100",
                    "x-ratelimit-remaining-tokens": "50000"
                },
                json=self._load_json_response("azure_sync.json", model)
            )
        )
        route_name = f"azure_{deployment_name}_sync"
        self._routes[route_name] = route
        return route

    def mock_openwebui_streaming(
        self,
        base_url: str,
        model: str = "gemma3:12b",
        status_code: int = 200
    ):
        """Mock OpenWebUI streaming response."""
        url_pattern = f"{base_url}/api/chat*"

        route = self.respx_mock.post(url__regex=url_pattern.replace("*", ".*")).mock(
            return_value=Response(
                status_code=status_code,
                headers={"content-type": "text/event-stream"},
                content=self._load_streaming_response("openwebui_streaming.txt", model)
            )
        )
        route_name = f"openwebui_{model}_streaming"
        self._routes[route_name] = route
        return route

    def mock_openwebui_sync(
        self,
        base_url: str,
        model: str = "gemma3:12b",
        status_code: int = 200
    ):
        """Mock OpenWebUI non-streaming response."""
        url_pattern = f"{base_url}/api/chat*"

        route = self.respx_mock.post(url__regex=url_pattern.replace("*", ".*")).mock(
            return_value=Response(
                status_code=status_code,
                headers={"content-type": "application/json"},
                json=self._load_json_response("openwebui_sync.json", model)
            )
        )
        route_name = f"openwebui_{model}_sync"
        self._routes[route_name] = route
        return route

    def mock_provider_failure(
        self,
        provider: str,
        base_url: str,
        deployment_name: Optional[str] = None
    ):
        """Mock provider returning error."""
        if provider == "azure":
            url_pattern = f"{base_url}/{deployment_name}/chat/completions*"
            route = self.respx_mock.post(url__regex=url_pattern.replace("*", ".*")).mock(
                return_value=Response(
                    status_code=500,
                    json={"error": {"message": "Provider error", "type": "internal_error"}}
                )
            )
            route_name = f"azure_{deployment_name}_failure"
        elif provider == "openwebui":
            url_pattern = f"{base_url}/api/chat*"
            route = self.respx_mock.post(url__regex=url_pattern.replace("*", ".*")).mock(
                return_value=Response(
                    status_code=500,
                    json={"error": "Provider error"}
                )
            )
            route_name = f"openwebui_failure"
        else:
            raise ValueError(f"Unknown provider: {provider}")

        self._routes[route_name] = route
        return route

    def verify_called(self, route_name: str, times: int = 1):
        """Verify a mock was called specific number of times."""
        route = self._routes.get(route_name)
        assert route, f"Route {route_name} not found in registered routes: {list(self._routes.keys())}"
        assert route.call_count == times, \
            f"Route {route_name}: expected {times} calls, got {route.call_count}"

    def verify_not_called(self, route_name: str):
        """Verify a mock was NOT called."""
        route = self._routes.get(route_name)
        if route:
            assert route.call_count == 0, \
                f"Route {route_name}: expected 0 calls, got {route.call_count}"

    def reset_call_counts(self):
        """Reset all call counts."""
        for route in self._routes.values():
            route.call_count = 0

    def _load_streaming_response(self, filename: str, model: str) -> bytes:
        """Load streaming response from file."""
        file_path = self._data_dir / filename
        if not file_path.exists():
            # Return default response
            return self._generate_default_streaming(model)

        with open(file_path, "rb") as f:
            content = f.read()

        # Replace model placeholder
        content = content.replace(b"{{MODEL}}", model.encode())
        return content

    def _load_json_response(self, filename: str, model: str) -> dict:
        """Load JSON response from file."""
        file_path = self._data_dir / filename
        if not file_path.exists():
            # Return default response
            return self._generate_default_json(model)

        with open(file_path, "r") as f:
            data = json.load(f)

        # Replace model placeholder
        if "model" in data:
            data["model"] = model

        return data

    def _generate_default_streaming(self, model: str) -> bytes:
        """Generate default streaming response."""
        chunks = [
            f'data: {{"id":"chatcmpl-test","object":"chat.completion.chunk","created":1234567890,"model":"{model}","choices":[{{"index":0,"delta":{{"role":"assistant","content":""}},"finish_reason":null}}]}}\n\n',
            f'data: {{"id":"chatcmpl-test","object":"chat.completion.chunk","created":1234567890,"model":"{model}","choices":[{{"index":0,"delta":{{"content":"Test"}},"finish_reason":null}}]}}\n\n',
            f'data: {{"id":"chatcmpl-test","object":"chat.completion.chunk","created":1234567890,"model":"{model}","choices":[{{"index":0,"delta":{{"content":" response"}},"finish_reason":null}}]}}\n\n',
            f'data: {{"id":"chatcmpl-test","object":"chat.completion.chunk","created":1234567890,"model":"{model}","choices":[{{"index":0,"delta":{{}},"finish_reason":"stop"}}],"usage":{{"prompt_tokens":10,"completion_tokens":2,"total_tokens":12}}}}\n\n',
            'data: [DONE]\n\n'
        ]
        return "".join(chunks).encode()

    def _generate_default_json(self, model: str) -> dict:
        """Generate default JSON response."""
        return {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1234567890,
            "model": model,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Test response"
                },
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 2,
                "total_tokens": 12
            }
        }
