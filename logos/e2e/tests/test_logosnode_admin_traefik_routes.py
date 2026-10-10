"""Static guard: Traefik must name every JWT logosnode admin path.

The orchestrator owns ``PathPrefix(/api/logosdb/providers/logosnode)`` at
priority 201. Spring's operator-facing actions need priority 202 exact-Path
entries on the webservice router, or Traefik sends the UI's JWT call to the
orchestrator, which has no such route and answers 404 Not Found. That is
what broke the Drain button when ``lanes/drain`` was added to Spring and the
UI but not to these lists.
"""

from __future__ import annotations

import re
from pathlib import Path

_LOGOS = Path(__file__).resolve().parents[2]
_UI_SERVICE = _LOGOS / "logos-ui" / "src" / "app" / "features" / "statistics" / "services" / "statistics.service.ts"
_COMPOSE_FILES = (
    _LOGOS / "docker-compose.yaml",
    _LOGOS / "docker-compose.dev.yaml",
    _LOGOS / "e2e" / "harness" / "stack" / "docker-compose.e2e.yaml",
)

_UI_PATH_RE = re.compile(r"""['"](/api/logosdb/providers/logosnode/[^'"]+)['"]""")
_ADMIN_RULE_RE = re.compile(r"traefik\.http\.routers\.(?:webservice-logosnode-admin|ws-logosnode-admin)\.rule=(.+)")


def _ui_logosnode_admin_paths() -> set[str]:
    text = _UI_SERVICE.read_text(encoding="utf-8")
    return set(_UI_PATH_RE.findall(text))


def _compose_admin_paths(compose: Path) -> set[str]:
    text = compose.read_text(encoding="utf-8")
    match = _ADMIN_RULE_RE.search(text)
    assert match, f"{compose.name} has no logosnode-admin Traefik rule"
    return set(re.findall(r"Path\(`([^`]+)`\)", match.group(1)))


def test_ui_logosnode_admin_paths_are_named_in_every_compose_admin_router() -> None:
    ui_paths = _ui_logosnode_admin_paths()
    assert ui_paths, "statistics.service.ts no longer posts to logosnode admin paths"
    assert "/api/logosdb/providers/logosnode/lanes/drain" in ui_paths

    for compose in _COMPOSE_FILES:
        named = _compose_admin_paths(compose)
        missing = sorted(ui_paths - named)
        assert not missing, (
            f"{compose.relative_to(_LOGOS)} omits Traefik exact-Path entries for "
            f"{missing}; without them the UI call reaches the orchestrator catch-all "
            "and returns 404 Not Found"
        )
