"""Which models a session may drive: local ones, and only local ones.

This runner exists to spend serving capacity that would otherwise idle. Local
capacity is already paid for; a cloud deployment bills per token. So agent
work must never reach a cloud model — not by naming one, not by naming an
alias of one, and not because the agent key was granted a cloud provider by
mistake.

The boundary itself is the platform's own key scoping: a Logos key reaches
exactly the deployments its key or team permissions grant, and the model
gateway replaces whatever credential a session sends with that key. Grant the
agent key local providers only and cloud is unreachable however the agent
asks for it — including through an alias, since an alias resolves to the
model it names and inherits that model's providers.

What this module adds is the refusal to *assume* that configuration is right.
It reads what the key can actually reach and turns it into one decision:

* every reachable deployment is local — sessions may run;
* any reachable deployment is a cloud provider — no session starts, and the
  reason names the models that would have cost money;
* the key does not resolve, or the database cannot be read — unknown, which
  is treated as unsafe rather than as permission.

The check runs at startup and on every scheduler pass, because permissions
are data: a key can be granted a cloud provider long after this service
started, and the next pass must notice.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Iterable

from . import db
from .config import settings

logger = logging.getLogger(__name__)

# Provider types that serve from hardware this platform runs itself. Mirrors
# the orchestrator's `normalize_provider_type`, whose 'logosnode' bucket is
# the only local one; everything it does not map into that bucket is either
# a cloud provider or a type this runner has never heard of. Both are
# refused — an unknown provider type is not evidence of a free one.
_LOCAL_PROVIDER_TYPES = frozenset(
    {
        "node",
        "node_controller",
        "ollama",
        "logos_worker_node",
        "logos-workernode",
        "logosnode",
    }
)


def is_local_provider_type(provider_type: str | None) -> bool:
    return (provider_type or "").strip().lower() in _LOCAL_PROVIDER_TYPES


def _names_of(row: dict[str, Any]) -> list[str]:
    """A deployment's model name and every alias that resolves to it.

    Model names are matched case-insensitively at the request boundary, so
    the policy compares in lower case too: 'Qwen3-8B' and 'qwen3-8b' are one
    model, and an alias of a cloud model is as expensive as its target.
    """
    names = [str(row.get("model_name") or "").strip().lower()]
    raw_aliases = row.get("aliases")
    if raw_aliases:
        names.extend(alias.strip().lower() for alias in str(raw_aliases).split(","))
    return [name for name in names if name]


@dataclass(frozen=True)
class ModelPolicy:
    """What the agent key can reach, and whether that is safe to run on."""

    # Names (and aliases) served exclusively by local providers.
    local_models: frozenset[str] = frozenset()
    # Names (and aliases) with at least one cloud deployment the key could be
    # routed to. Non-empty means the key can spend money.
    cloud_models: frozenset[str] = frozenset()
    # The local model names without their aliases, in display order. This is
    # what the UI offers and what a single-model deployment defaults to.
    offered: tuple[str, ...] = ()
    ok: bool = False
    detail: str = "model policy not evaluated yet"
    # Set when the policy could not be established at all (no database, no
    # key). Distinguished from a clean 'nothing reachable' so the UI and the
    # logs can say which it was.
    unknown: bool = True

    @property
    def default_model(self) -> str:
        """The model a session that names none is driven by.

        Configuration wins when it is set and local. Otherwise a deployment
        that serves exactly one model locally needs no configuration at all:
        there is only one answer, so the runner uses it rather than making
        every session repeat it.
        """
        configured = settings.default_model.strip()
        if configured:
            return configured if configured.lower() in self.local_models else ""
        return self.offered[0] if len(self.offered) == 1 else ""

    def resolve(self, model: str | None) -> str:
        """The model name a session will actually be driven by."""
        named = (model or "").strip()
        return named or self.default_model

    def allows(self, model: str | None) -> bool:
        """Whether a session may be driven by this model name."""
        if not self.ok:
            return False
        resolved = self.resolve(model)
        return bool(resolved) and resolved.lower() in self.local_models

    def refusal(self, model: str | None) -> str:
        """Why a model was refused, in the words the operator needs."""
        if not self.ok:
            return f"no model may be used: {self.detail}"
        name = self.resolve(model)
        if not name:
            configured = settings.default_model.strip()
            if configured:
                return (
                    f"the configured default model '{configured}' is not served locally "
                    f"by this runner's key ({self.summary()})"
                )
            return (
                f"no model was named, and this key reaches several local models, so "
                f"there is no single default to fall back on ({self.summary()}). "
                f"Name one, or set LOGOS_AGENT_DEFAULT_MODEL."
            )
        if name.lower() in self.cloud_models:
            return (
                f"'{name}' is served by a cloud provider; agent sessions may only "
                f"use models this platform serves itself"
            )
        return f"'{name}' is not among the locally served models this runner's key may use ({self.summary()})"

    def summary(self) -> str:
        if not self.offered:
            return "no local models reachable"
        shown = ", ".join(self.offered[:8])
        if len(self.offered) > 8:
            shown += f", … ({len(self.offered)} in total)"
        return shown


UNKNOWN = ModelPolicy()


def classify(rows: Iterable[dict[str, Any]]) -> tuple[frozenset[str], frozenset[str], tuple[str, ...]]:
    """Split reachable deployments into local-only and cloud-tainted names.

    A model with both a local and a cloud deployment counts as cloud: the
    scheduler is free to route to either, so the cheap one being available is
    no guarantee the expensive one is not used.

    Returns the local names, the cloud names, and the local *model* names on
    their own — aliases are accepted in a request but would be noise in a
    list of what can be picked.
    """
    local: set[str] = set()
    cloud: set[str] = set()
    primary: dict[str, str] = {}
    for row in rows:
        names = _names_of(row)
        if not names:
            continue
        if is_local_provider_type(row.get("provider_type")):
            local.update(names)
            primary.setdefault(names[0], str(row.get("model_name") or "").strip())
        else:
            cloud.update(names)
    local_only = frozenset(local - cloud)
    offered = tuple(sorted(display for key, display in primary.items() if key in local_only))
    return local_only, frozenset(cloud), offered


def evaluate(rows: Iterable[dict[str, Any]]) -> ModelPolicy:
    """Turn reachable deployments into the runner's local-only decision."""
    local, cloud, offered = classify(rows)
    if cloud:
        listed = ", ".join(sorted(cloud)[:8])
        return ModelPolicy(
            local_models=local,
            cloud_models=cloud,
            offered=offered,
            ok=False,
            unknown=False,
            detail=(
                f"the agent key can reach {len(cloud)} cloud-served model(s) ({listed}). "
                f"Agent work must never bill a cloud provider — remove the cloud "
                f"providers from this key's (or its team's) permissions."
            ),
        )
    if not local:
        return ModelPolicy(
            ok=False,
            unknown=False,
            detail="the agent key reaches no locally served model, so there is nothing a session could be driven by",
        )
    return ModelPolicy(
        local_models=local,
        cloud_models=frozenset(),
        offered=offered,
        ok=True,
        unknown=False,
        detail=f"{len(offered)} locally served model(s) reachable, no cloud provider",
    )


async def load() -> ModelPolicy:
    """Read the agent key's reachable deployments and evaluate them."""
    if not settings.agent_api_key:
        return ModelPolicy(detail="LOGOS_AGENT_API_KEY is not configured")
    try:
        if not await db.agent_key_exists(settings.agent_api_key):
            return ModelPolicy(
                detail=(
                    "LOGOS_AGENT_API_KEY is not an active key of this platform, "
                    "so the models it may reach cannot be established"
                )
            )
        rows = await db.reachable_deployments(settings.agent_api_key)
    except Exception as exc:  # database down, schema drift, anything
        logger.warning("could not read the agent key's model permissions: %s", exc)
        return ModelPolicy(detail=f"model permissions unreadable: {exc}")
    return evaluate(rows)


_current: ModelPolicy = UNKNOWN


def current() -> ModelPolicy:
    """The most recent evaluation, without touching the database."""
    return _current


async def refresh() -> ModelPolicy:
    """Re-evaluate and remember. Logs transitions, not every pass."""
    global _current
    policy = await load()
    if policy.ok != _current.ok or policy.detail != _current.detail:
        if policy.ok:
            logger.info("model policy: %s", policy.detail)
        else:
            logger.error("model policy refuses agent work: %s", policy.detail)
    _current = policy
    return policy
