"""
Cross-checks for the example configuration files.

The example configuration must stay usable as-is: every model id it
references must exist in the example catalog, and every local slot must
name an entry the local environment can actually serve (an Ollama model,
or an OpenAI-compatible entry with an explicit base_url). A vendor entry
(``api_key`` authentication, no base_url) only answers from the cloud and
must never sit in a local slot.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
APPLICATION_EXAMPLE = REPO_ROOT / "application.example.yml"
LLM_CONFIG_EXAMPLE = REPO_ROOT / "llm_config.example.yml"


def _catalog() -> dict:
    with LLM_CONFIG_EXAMPLE.open(encoding="utf-8") as f:
        entries = yaml.safe_load(f)
    return {entry["id"]: entry for entry in entries}


def _collect(node, path, refs):
    """Collect ``(path, env, model_id)`` for every model slot under node.

    A slot is a ``local``/``cloud`` pair on a role, a flat string (e.g.
    embedding, reranker) or a list of ids (memiris embeddings).
    """
    if isinstance(node, dict):
        if "local" in node or "cloud" in node:
            for env in ("local", "cloud"):
                value = node.get(env)
                if value:
                    refs.append((f"{path}.{env}", env, value))
            return
        for key, value in node.items():
            _collect(value, f"{path}.{key}", refs)
    elif isinstance(node, list):
        for index, item in enumerate(node):
            item_path = f"{path}[{index}]"
            if isinstance(item, str) and item:
                refs.append((item_path, None, item))
            else:
                _collect(item, item_path, refs)


def _model_references():
    with APPLICATION_EXAMPLE.open(encoding="utf-8") as f:
        app = yaml.safe_load(f)
    refs = []
    _collect(app["llm_configuration"], "llm_configuration", refs)
    _collect(app["memiris"]["llm_configuration"], "memiris.llm_configuration", refs)
    return refs


def _is_locally_servable(entry):
    if entry.get("type") == "ollama":
        return True
    return entry.get("type") == "openai_chat" and bool(entry.get("base_url"))


def test_application_example_references_only_example_catalog_ids():
    catalog = _catalog()
    unknown = [
        f"{where} -> '{model_id}'"
        for where, _env, model_id in _model_references()
        if model_id not in catalog
    ]
    assert not unknown, "Model ids missing from llm_config.example.yml:\n" + "\n".join(
        unknown
    )


def test_application_example_local_slots_use_locally_servable_models():
    catalog = _catalog()
    misplaced = []
    for where, env, model_id in _model_references():
        if env != "local":
            continue
        entry = catalog.get(model_id)
        if entry is None:
            misplaced.append(f"{where} -> '{model_id}' is missing from the catalog")
        elif not _is_locally_servable(entry):
            misplaced.append(
                f"{where} -> '{model_id}' (type {entry.get('type')!r}) "
                "cannot be served locally"
            )
    assert not misplaced, (
        "Local slots must name models the local environment can serve "
        "(Ollama, or OpenAI-compatible with a base_url):\n" + "\n".join(misplaced)
    )
