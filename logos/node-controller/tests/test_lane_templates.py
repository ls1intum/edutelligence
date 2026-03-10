from __future__ import annotations

import pytest

from node_controller.admin_api import get_lane_templates


@pytest.mark.asyncio
async def test_lane_templates_payload_shape() -> None:
    payload = await get_lane_templates()

    assert "notes" in payload
    assert "templates" in payload

    templates = payload["templates"]
    assert "single_ollama_lane" in templates
    assert "single_vllm_lane" in templates
    assert "mixed_lanes" in templates
