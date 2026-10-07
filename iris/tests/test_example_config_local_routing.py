from pathlib import Path

import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent


def _load(name: str):
    with open(CONFIG_DIR / name, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _is_locally_served(entry: dict) -> bool:
    """A model is locally served when it runs on a self-hosted endpoint: an
    Ollama model, or an OpenAI-compatible gateway with an explicit base_url.
    Plain OpenAI/Azure entries (no base_url) hit the vendor's cloud."""
    entry_type = entry.get("type", "")
    if entry_type == "ollama":
        return True
    return entry_type.startswith("openai") and bool(entry.get("base_url"))


def _local_model_ids(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "local" and isinstance(value, str):
                yield value
            else:
                yield from _local_model_ids(value)
    elif isinstance(node, list):
        for item in node:
            yield from _local_model_ids(item)


def test_local_assignments_resolve_to_locally_served_models():
    # On-premise routing must keep student data on the university network: every
    # `local:` assignment must point at a model served on a self-hosted endpoint,
    # never at a model that defaults to an external OpenAI/Azure endpoint.
    catalog = {
        entry["id"]: entry
        for entry in _load("llm_config.example.yml")
        if isinstance(entry, dict) and "id" in entry
    }
    local_ids = list(_local_model_ids(_load("application.example.yml")))
    assert local_ids, "expected at least one local: assignment in the example config"
    external = [
        model_id
        for model_id in local_ids
        if model_id in catalog and not _is_locally_served(catalog[model_id])
    ]
    assert external == [], (
        "local: assignments must stay on locally-served models; these resolve "
        f"to an external endpoint: {external}"
    )
