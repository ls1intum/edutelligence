"""
Integration tests for PROXY mode on sync endpoints.

Tests direct forwarding without classification or scheduling.
"""

import pytest
from httpx import AsyncClient


class TestSyncProxyStreaming:
    """Test PROXY mode with streaming responses."""

    @pytest.mark.asyncio
    @pytest.mark.respx
    async def test_openai_proxy_streaming_azure(
        self, logos_client, logos_key, mock_providers, verification, azure_test_model, db_manager
    ):
        """Test #1: /openai/ + PROXY + Streaming (Azure)"""

        # Get Azure model details from database
        model = azure_test_model
        provider = db_manager.get_provider(model["provider_id"])

        # Setup mock
        mock_providers.mock_azure_streaming(
            base_url=provider["base_url"],
            deployment_name=model["deployment_name"],
            model=model["name"]
        )

        # Execute request
        response = await logos_client.post(
            "/openai/chat/completions",
            headers={
                "logos_key": logos_key,
                "api_key": "test-azure-key",
                "deployment_name": model["deployment_name"],
                "api_version": "2024-08-01-preview"
            },
            json={
                "model": model["name"],  # PROXY mode - model specified
                "messages": [{"role": "user", "content": "Test message"}],
                "stream": True
            }
        )

        # Verify response
        assert response.status_code == 200
        verification.assert_streaming_response(response.headers)

        # Verify SSE content
        content = response.text
        verification.assert_sse_format(content)

        # Verify provider was called
        mock_providers.verify_called(f"azure_{model['deployment_name']}_streaming", times=1)

        # Verify database logging
        log = verification.assert_request_logged(response.headers)
        verification.assert_usage_logged(log)
        verification.assert_proxy_mode(log)  # No classification/scheduling

    @pytest.mark.asyncio
    @pytest.mark.respx
    async def test_v1_proxy_streaming_azure(
        self, logos_client, logos_key, mock_providers, verification, azure_test_model, db_manager
    ):
        """Test #5: /v1/ + PROXY + Streaming (Azure)"""

        model = azure_test_model
        provider = db_manager.get_provider(model["provider_id"])

        mock_providers.mock_azure_streaming(
            base_url=provider["base_url"],
            deployment_name=model["deployment_name"],
            model=model["name"]
        )

        response = await logos_client.post(
            "/v1/chat/completions",
            headers={
                "logos_key": logos_key,
                "api_key": "test-azure-key",
                "deployment_name": model["deployment_name"],
                "api_version": "2024-08-01-preview"
            },
            json={
                "model": model["name"],
                "messages": [{"role": "user", "content": "Test message"}],
                "stream": True
            }
        )

        assert response.status_code == 200
        verification.assert_streaming_response(response.headers)

        log = verification.assert_request_logged(response.headers)
        verification.assert_proxy_mode(log)


class TestSyncProxyNonStreaming:
    """Test PROXY mode with non-streaming responses."""

    @pytest.mark.asyncio
    @pytest.mark.respx
    async def test_openai_proxy_sync_azure(
        self, logos_client, logos_key, mock_providers, verification, azure_test_model, db_manager
    ):
        """Test #2: /openai/ + PROXY + Non-Streaming (Azure)"""

        model = azure_test_model
        provider = db_manager.get_provider(model["provider_id"])

        mock_providers.mock_azure_sync(
            base_url=provider["base_url"],
            deployment_name=model["deployment_name"],
            model=model["name"]
        )

        response = await logos_client.post(
            "/openai/chat/completions",
            headers={
                "logos_key": logos_key,
                "api_key": "test-azure-key",
                "deployment_name": model["deployment_name"],
                "api_version": "2024-08-01-preview"
            },
            json={
                "model": model["name"],
                "messages": [{"role": "user", "content": "Test message"}],
                "stream": False
            }
        )

        assert response.status_code == 200
        verification.assert_json_response(response.headers)

        # Verify response content
        data = response.json()
        verification.assert_response_has_content(data)
        assert data["usage"]["total_tokens"] > 0

        # Verify provider called
        mock_providers.verify_called(f"azure_{model['deployment_name']}_sync", times=1)

        # Verify logging
        log = verification.assert_request_logged(response.headers)
        verification.assert_usage_logged(log)
        verification.assert_proxy_mode(log)

    @pytest.mark.asyncio
    @pytest.mark.respx
    async def test_v1_proxy_sync_azure(
        self, logos_client, logos_key, mock_providers, verification, azure_test_model, db_manager
    ):
        """Test #6: /v1/ + PROXY + Non-Streaming (Azure)"""

        model = azure_test_model
        provider = db_manager.get_provider(model["provider_id"])

        mock_providers.mock_azure_sync(
            base_url=provider["base_url"],
            deployment_name=model["deployment_name"],
            model=model["name"]
        )

        response = await logos_client.post(
            "/v1/chat/completions",
            headers={
                "logos_key": logos_key,
                "api_key": "test-azure-key",
                "deployment_name": model["deployment_name"],
                "api_version": "2024-08-01-preview"
            },
            json={
                "model": model["name"],
                "messages": [{"role": "user", "content": "Test message"}],
                "stream": False
            }
        )

        assert response.status_code == 200
        data = response.json()
        verification.assert_response_has_content(data)

        log = verification.assert_request_logged(response.headers)
        verification.assert_proxy_mode(log)

    @pytest.mark.asyncio
    @pytest.mark.respx
    async def test_openai_proxy_sync_openwebui(
        self, logos_client, logos_key, mock_providers, verification, openwebui_test_model, db_manager
    ):
        """Test PROXY mode with OpenWebUI provider"""

        model = openwebui_test_model
        provider = db_manager.get_provider(model["provider_id"])

        mock_providers.mock_openwebui_sync(
            base_url=provider["base_url"],
            model=model["name"]
        )

        response = await logos_client.post(
            "/openai/chat/completions",
            headers={
                "logos_key": logos_key,
                "Authorization": "Bearer test-token"
            },
            json={
                "model": model["name"],
                "messages": [{"role": "user", "content": "Test message"}],
                "stream": False
            }
        )

        assert response.status_code == 200
        data = response.json()
        verification.assert_response_has_content(data)

        log = verification.assert_request_logged(response.headers)
        verification.assert_proxy_mode(log)
