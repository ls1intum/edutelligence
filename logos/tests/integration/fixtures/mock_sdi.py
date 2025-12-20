"""
Mock Ollama /ps endpoint for scheduling data.
Simulates cold-start and warm model scenarios.
"""

from typing import Dict, List
from datetime import datetime, timezone, timedelta


class SDIMocker:
    """Mock Ollama /ps endpoint for scheduling data."""

    def __init__(self, mocker):
        self.mocker = mocker
        self._loaded_models: Dict[str, dict] = {}
        self._mock_applied = False

    def set_loaded_models(self, models: List[dict]):
        """
        Set which models are loaded in VRAM.

        Args:
            models: List of dicts with keys:
                - name: Model name (e.g., 'gemma3:12b')
                - size_vram: VRAM usage in bytes (optional, default 8GB)
                - expires_at: ISO timestamp or None (auto-calculated)
        """
        self._loaded_models = {}
        for model in models:
            expires_at = model.get("expires_at")
            if not expires_at:
                # Default: 5 minutes from now
                expires_at = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()

            self._loaded_models[model["name"]] = {
                "name": model["name"],
                "model": model["name"],  # Ollama API returns both 'name' and 'model'
                "size_vram": model.get("size_vram", 8 * 1024 * 1024 * 1024),  # Default 8GB
                "expires_at": expires_at
            }

    def set_cold_start(self, model_name: str):
        """Mark model as not loaded (cold start scenario)."""
        if model_name in self._loaded_models:
            del self._loaded_models[model_name]

    def set_warm_model(self, model_name: str, vram_mb: int = 8192):
        """Mark model as loaded in VRAM (warm scenario)."""
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        self._loaded_models[model_name] = {
            "name": model_name,
            "model": model_name,
            "size_vram": vram_mb * 1024 * 1024,
            "expires_at": expires_at
        }

    def set_all_cold(self):
        """Mark all models as not loaded (cold start for all)."""
        self._loaded_models = {}

    def apply_mock(self):
        """Apply the mock to OllamaDataProvider._fetch_ps_via_http."""
        if self._mock_applied:
            return  # Already applied

        def mock_fetch_ps(*args, **kwargs):
            # Return the mocked /ps response
            return {
                "models": list(self._loaded_models.values())
            }

        self.mocker.patch(
            "logos.sdi.providers.ollama_provider.OllamaDataProvider._fetch_ps_via_http",
            side_effect=mock_fetch_ps
        )
        self._mock_applied = True

    def get_current_state(self) -> dict:
        """Get current mocked state for debugging."""
        return {
            "loaded_models": list(self._loaded_models.keys()),
            "total_models": len(self._loaded_models),
            "total_vram_mb": sum(m["size_vram"] for m in self._loaded_models.values()) // (1024 * 1024)
        }
