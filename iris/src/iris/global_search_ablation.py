"""In-process ablation sweep (THROWAWAY) for per-component attribution.

For each ablation config it toggles the six ``gsa_*`` component flags and runs a
DETERMINISTIC, retrieval-only pass over the labeled golden battery — no answer
LLM is called, so there is no sampling noise and no repeats are needed. One
deploy sweeps every config; parse the ``[ablation]`` lines offline to compute
per-component deltas (add-one = effect in isolation; leave-one-out = effect in
the full stack; the gap between them = interaction).

Components (each defaults on = branch behaviour; off = old/main-like):
  gsa_instruct     Qwen3 instruction prefix on the query embedding
  gsa_alpha_high   hybrid alpha 0.75 (vs 0.5)
  gsa_deep_lanes   deep candidate lanes (vs fetch only `limit`)
  gsa_dedupe       snippet dedupe
  gsa_metadata_fix duplicate-safe LectureUnits fetch limit (vs the truncation bug)
  gsa_rerank       two-stage reranker + threshold gate (vs fused ordering)

Metrics per config (retrieval-only, deterministic):
  top1 / top5   labeled-source hit rate (ranking + recall; the metadata-fix,
                instruct, alpha, deep-lanes, rerank all move this)
  dup_rate      fraction of labeled queries whose top-5 contains a byte-identical
                snippet copy (dedupe moves this)
  control_leak  fraction of no-content controls that still return >=1 result
                (the rerank threshold gate moves this)
"""

from __future__ import annotations

import logging
import time

from iris.common.logging_config import get_logger
from iris.config import settings
from iris.global_search_battery_data import QUERIES, VERSION

logger = get_logger(__name__)

_PREFIX = "[ablation]"
_STARTUP_DELAY_S = 45.0  # let census / embedding warm-up finish first
_FACTORS = [
    "gsa_instruct",
    "gsa_alpha_high",
    "gsa_deep_lanes",
    "gsa_dedupe",
    "gsa_metadata_fix",
    "gsa_rerank",
]


def _configs() -> list[tuple[str, dict[str, bool]]]:
    """baseline (all off) + full (all on) + add-one + leave-one-out."""
    cfgs: list[tuple[str, dict[str, bool]]] = [
        ("baseline_all_off", {f: False for f in _FACTORS}),
        ("full_all_on", {f: True for f in _FACTORS}),
    ]
    for f in _FACTORS:
        add_one = {x: False for x in _FACTORS}
        add_one[f] = True
        cfgs.append((f"AO_{f}", add_one))
    for f in _FACTORS:
        leave_out = {x: True for x in _FACTORS}
        leave_out[f] = False
        cfgs.append((f"LOO_{f}", leave_out))
    return cfgs


def _norm(value: str | None) -> str:
    return (value or "").casefold().strip()


def _matches(expect: dict, course: str | None, unit: str | None) -> bool:
    want_course, want_unit = _norm(expect.get("course")), _norm(expect.get("unit"))
    if want_unit and want_unit == _norm(unit):
        return True
    if want_course and want_course == _norm(course):
        return True
    return False


def _apply(cfg: dict[str, bool]) -> None:
    for flag, value in cfg.items():
        setattr(settings, flag, value)


def _eval(retriever, items: list[dict]) -> dict[str, float]:
    labeled_n = top1 = top5 = dup = 0
    control_n = control_leak = 0
    for item in items:
        expect = item["expect"]
        try:
            results = retriever.search(query=item["text"], limit=10)
        except Exception:  # noqa: BLE001 - one bad query must not stop the sweep
            continue
        top = results[:5]
        if expect.get("course") or expect.get("unit"):
            labeled_n += 1
            positions = [
                i
                for i, r in enumerate(top)
                if _matches(expect, r.course.name, r.lecture_unit.name)
            ]
            if positions:
                top5 += 1
            if positions and positions[0] == 0:
                top1 += 1
            keys = [(r.snippet or "")[:100].casefold().strip() for r in top]
            if keys and max(keys.count(k) for k in keys) > 1:
                dup += 1
        elif expect["outcome"] == "no_sources":
            control_n += 1
            if results:
                control_leak += 1
    return {
        "labeled_n": labeled_n,
        "top1": top1 / labeled_n if labeled_n else 0.0,
        "top5": top5 / labeled_n if labeled_n else 0.0,
        "dup_rate": dup / labeled_n if labeled_n else 0.0,
        "control_n": control_n,
        "control_leak": control_leak / control_n if control_n else 0.0,
    }


def run_ablation() -> None:
    """Run the config sweep and log one [ablation] line per config/scope."""
    try:
        time.sleep(_STARTUP_DELAY_S)
        # Silence the per-hit [LectureSearch] INFO spam for the whole sweep.
        logging.getLogger(
            "iris.retrieval.lecture.lecture_global_search_retrieval"
        ).setLevel(logging.WARNING)
        # Disable Langfuse/OTLP tracing for the sweep: thousands of traced
        # retrieval calls produce span batches that overflow the collector's
        # nginx body limit (413) and flood the log. @observe reads this flag
        # live, so flipping it here makes every span a no-op for the sweep.
        settings.langfuse.enabled = False
        try:
            from iris.tracing import (  # noqa: E402 pylint: disable=import-outside-toplevel
                shutdown_langfuse,
            )

            shutdown_langfuse()
        except Exception:  # noqa: BLE001 - best effort; tracing may be off already
            pass

        from iris.retrieval.lecture.lecture_global_search_retrieval import (  # noqa: E402 pylint: disable=import-outside-toplevel
            LectureGlobalSearchRetrieval,
        )
        from iris.vector_database.database import (  # noqa: E402 pylint: disable=import-outside-toplevel
            VectorDatabase,
        )

        client = VectorDatabase().get_client()
        # Flags are read at use-time, so one retriever instance serves every
        # config (gsa_rerank gates usage, not the model resolution in __init__).
        retriever = LectureGlobalSearchRetrieval(client)

        original = {f: getattr(settings, f) for f in _FACTORS}
        all_items = [dict(x) for x in QUERIES]
        held = [x for x in all_items if x.get("split") == "heldout"]
        cfgs = _configs()
        logger.info(
            "%s START battery_version=%s configs=%d queries=%d heldout=%d "
            "factors=%s",
            _PREFIX,
            VERSION,
            len(cfgs),
            len(all_items),
            len(held),
            ",".join(_FACTORS),
        )
        try:
            for name, cfg in cfgs:
                _apply(cfg)
                flags = "".join("1" if cfg[f] else "0" for f in _FACTORS)
                for scope, items in (("ALL", all_items), ("HELDOUT", held)):
                    m = _eval(retriever, items)
                    logger.info(
                        "%s cfg=%-24s %-7s flags=%s | labeled n=%d top1=%.3f "
                        "top5=%.3f dup=%.3f | control n=%d leak=%.3f",
                        _PREFIX,
                        name,
                        scope,
                        flags,
                        m["labeled_n"],
                        m["top1"],
                        m["top5"],
                        m["dup_rate"],
                        m["control_n"],
                        m["control_leak"],
                    )
        finally:
            _apply(original)
        logger.info(
            "%s DONE (flag order in `flags=` is: %s)", _PREFIX, " ".join(_FACTORS)
        )
    except Exception as e:  # noqa: BLE001 - the sweep must never break the service
        logger.warning("%s aborted: %s", _PREFIX, e, exc_info=True)
