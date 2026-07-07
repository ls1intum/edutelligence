"""
Retrieval-quality evaluation (Phase 2 of the results-gathering plan).

Two steps:
 1. --make-sheet   Build a labeling sheet: for each lecture-content query, pool the
                   top-K candidates from every retrieval config (raw query at several
                   alphas + HyDE at 0.5). YOU then fill the `relevance` column:
                   2 = directly answers, 1 = related/partial, 0 = irrelevant.
 2. --score        Compute nDCG@5, MRR, Recall@5/10 per config from the labeled
                   sheet, with paired bootstrap CIs on the HyDE-vs-raw delta.

Usage:
  .venv/bin/python eval/eval_retrieval.py --make-sheet
  # ... label eval/data/retrieval_labels.csv ...
  .venv/bin/python eval/eval_retrieval.py --score
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("APPLICATION_YML_PATH", str(REPO_ROOT / "application.local.yml"))
os.environ.setdefault("LLM_CONFIG_PATH", str(REPO_ROOT / "llm_config.local.yml"))
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "eval/data"))

from iris.config import settings  # noqa: E402

settings.set_env_vars()

import logging  # noqa: E402

for noisy in ("httpx", "weaviate", "langfuse", "urllib3", "openai", "httpcore"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
logging.getLogger("iris").setLevel(logging.WARNING)

LABELS_CSV = REPO_ROOT / "eval/data/retrieval_labels.csv"
K_POOL = 10  # candidates per config in the labeling pool

# Retrieval configs: (name, use_hyde, alpha)
CONFIGS = [
    ("raw_a00", False, 0.0),  # pure BM25
    ("raw_a025", False, 0.25),
    ("raw_a05", False, 0.5),
    ("raw_a075", False, 0.75),
    ("raw_a10", False, 1.0),  # pure vector
    ("hyde_a05", True, 0.5),  # production config
]

# Lecture-content categories from the 150-question suite (entity/out-of-scope
# categories have no lecture gold and are excluded from retrieval labeling).
LECTURE_CATEGORIES = {"DL/smart", "DL/basic", "DL/typos", "PSE", "concurrent"}


def doc_key(dto) -> str:
    """Stable identity for one retrievable item: unit + page."""
    return f"{dto.lecture_unit.id}:{dto.lecture_unit.page_number}"


def make_sheet() -> None:
    from answer_suite import QUESTIONS
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate

    from iris.llm import CompletionArguments, LlmRequestHandler
    from iris.llm.langchain import IrisLangchainChatModel
    from iris.llm.llm_configuration import resolve_model
    from iris.pipeline.prompts.global_search_prompts import hyde_system_prompt
    from iris.retrieval.lecture.lecture_global_search_retrieval import (
        LectureGlobalSearchRetrieval,
    )
    from iris.vector_database.database import VectorDatabase

    client = VectorDatabase().get_client()
    retriever = LectureGlobalSearchRetrieval(client, local=True)
    hyde_model = resolve_model("global_search_pipeline", "default", "hyde", local=True)
    hyde_chain = (
        ChatPromptTemplate.from_messages(
            [("system", hyde_system_prompt), ("user", "{query}")]
        )
        | IrisLangchainChatModel(
            request_handler=LlmRequestHandler(model_id=hyde_model),
            completion_args=CompletionArguments(
                reasoning_effort="none", max_tokens=150
            ),
        )
        | StrOutputParser()
    )

    queries = [
        (q, ctx, cat) for q, ctx, cat, _ in QUESTIONS if cat in LECTURE_CATEGORIES
    ]
    print(f"Building candidate pool for {len(queries)} lecture-content queries…")

    rows = []
    for i, (query, ctx, cat) in enumerate(queries, 1):
        hyde_text = hyde_chain.invoke({"query": query})
        pool: dict[str, dict] = {}
        ranks: dict[str, dict[str, int]] = defaultdict(dict)
        for name, use_hyde, alpha in CONFIGS:
            vector_text = hyde_text if use_hyde else query
            results = retriever.search_with_vector_override(
                query=query,
                vector_text=vector_text,
                alpha=alpha,
                limit=K_POOL,
                access_context=ctx,
            )
            for rank, (_score, dto) in enumerate(results, 1):
                key = doc_key(dto)
                ranks[key][name] = rank
                if key not in pool:
                    pool[key] = {
                        "unit": dto.lecture_unit.name or dto.lecture_unit.id,
                        "page": dto.lecture_unit.page_number,
                        "snippet": (dto.snippet or "")[:220].replace("\n", " "),
                    }
        for key, meta in pool.items():
            rows.append(
                {
                    "query": query,
                    "category": cat,
                    "doc": key,
                    "unit": meta["unit"],
                    "page": meta["page"],
                    "snippet": meta["snippet"],
                    **{name: ranks[key].get(name, "") for name, _, _ in CONFIGS},
                    "relevance": "",
                }
            )
        print(f"[{i}/{len(queries)}] pool={len(pool)} {query[:55]}", flush=True)

    client.close()
    with open(LABELS_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\nLabeling sheet: {LABELS_CSV} ({len(rows)} rows)")
    print("Fill `relevance`: 2 = directly answers, 1 = related, 0 = irrelevant.")


def dcg(rels: list[float]) -> float:
    return sum(r / np.log2(i + 2) for i, r in enumerate(rels))


def score() -> None:
    with open(LABELS_CSV, encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f)]
    labeled = [r for r in rows if r["relevance"].strip() != ""]
    if not labeled:
        raise SystemExit("No labeled rows — fill the relevance column first.")
    print(f"{len(labeled)}/{len(rows)} rows labeled")

    by_query: dict[str, list[dict]] = defaultdict(list)
    for r in labeled:
        by_query[r["query"]].append(r)

    config_names = [name for name, _, _ in CONFIGS]
    per_query: dict[str, dict[str, dict]] = defaultdict(dict)
    for query, items in by_query.items():
        rel = {r["doc"]: float(r["relevance"]) for r in items}
        n_rel = sum(1 for v in rel.values() if v > 0)
        ideal = sorted(rel.values(), reverse=True)[:5]
        for name in config_names:
            ranked = sorted([r for r in items if r[name]], key=lambda r: int(r[name]))
            rels = [rel[r["doc"]] for r in ranked]
            ndcg5 = dcg(rels[:5]) / dcg(ideal) if dcg(ideal) > 0 else 0.0
            rr = next((1 / (i + 1) for i, v in enumerate(rels) if v > 0), 0.0)
            rec5 = sum(1 for v in rels[:5] if v > 0) / n_rel if n_rel else 0.0
            rec10 = sum(1 for v in rels[:10] if v > 0) / n_rel if n_rel else 0.0
            per_query[query][name] = {
                "ndcg5": ndcg5,
                "mrr": rr,
                "rec5": rec5,
                "rec10": rec10,
            }

    print(f"\n{'config':<10} {'nDCG@5':>8} {'MRR':>8} {'R@5':>8} {'R@10':>8}")
    for name in config_names:
        vals = [per_query[q][name] for q in per_query]
        print(
            f"{name:<10} "
            f"{np.mean([v['ndcg5'] for v in vals]):>8.3f} "
            f"{np.mean([v['mrr'] for v in vals]):>8.3f} "
            f"{np.mean([v['rec5'] for v in vals]):>8.3f} "
            f"{np.mean([v['rec10'] for v in vals]):>8.3f}"
        )

    # paired bootstrap: hyde_a05 vs raw_a05 on nDCG@5
    qs = list(per_query.keys())
    deltas = np.array(
        [
            per_query[q]["hyde_a05"]["ndcg5"] - per_query[q]["raw_a05"]["ndcg5"]
            for q in qs
        ]
    )
    rng = np.random.default_rng(42)
    idx = rng.integers(0, len(deltas), size=(10_000, len(deltas)))
    boot = deltas[idx].mean(axis=1)
    print(
        f"\nHyDE vs raw (α=0.5) ΔnDCG@5: {deltas.mean():+.3f} "
        f"(95% CI [{np.percentile(boot, 2.5):+.3f}, "
        f"{np.percentile(boot, 97.5):+.3f}], n={len(deltas)} queries)"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--make-sheet", action="store_true")
    g.add_argument("--score", action="store_true")
    args = ap.parse_args()
    if args.make_sheet:
        make_sheet()
    else:
        score()


if __name__ == "__main__":
    main()
