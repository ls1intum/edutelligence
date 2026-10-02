"""Merge raw Prometheus exposition text from multiple upstream sources.

Used to fold every connected worker's already lane-merged vLLM ``/metrics``
text into one deduplicated set of metric families, relabeling each worker's
samples so identical metric names from different workers don't collide into
a single, ambiguous series.
"""

from __future__ import annotations

import logging
from typing import Iterable

from prometheus_client.core import Metric
from prometheus_client.parser import text_string_to_metric_families

logger = logging.getLogger("LogosLogger")


def merge_metric_families(sources: Iterable[tuple[dict[str, str], str]]) -> list[Metric]:
    """Parse each (extra_labels, prometheus_text) source and merge by metric name.

    A metric name's HELP/TYPE is taken from whichever source is parsed first;
    every source's samples are relabeled with its own `extra_labels` and
    appended to that one family. Prometheus then sees a single family per
    metric name, with a distinguishing label (e.g. `worker_id`) per sample
    instead of colliding series or repeated HELP/TYPE blocks.
    """
    families: dict[str, Metric] = {}
    order: list[str] = []
    for extra_labels, text in sources:
        if not text:
            continue
        try:
            parsed = list(text_string_to_metric_families(text))
        except ValueError:
            logger.debug("Failed to parse upstream Prometheus metrics text", exc_info=True)
            continue
        for family in parsed:
            target = families.get(family.name)
            if target is None:
                target = Metric(family.name, family.documentation, family.type)
                families[family.name] = target
                order.append(family.name)
            for sample in family.samples:
                target.samples.append(sample._replace(labels={**sample.labels, **extra_labels}))
    return [families[name] for name in order]
