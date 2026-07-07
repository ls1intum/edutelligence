"""
LLM-as-judge scoring of generated answers (Phase 5 of the results-gathering plan).

Reads an answers_*.jsonl produced by eval_answer_pipeline.py and scores every
ANSWERED query on:
  - faithfulness   (1-5): every claim supported by the provided sources
  - completeness   (1-5): covers all relevant sources, not just the first
  - language_match (bool): answer language equals query language
  - citation_support: per cited source, does it actually support the answer
Length compliance (<=300 words) is computed locally, not judged.

The judge model must differ from the answer model. A random 30-answer sample is
flagged `human_validation: true` for independent human scoring (judge validation).

Usage:
  .venv/bin/python eval/eval_answer_judge.py eval/results/answers_<stamp>.jsonl \
      [--mode full] [--judge-model personal-openai-gpt-5.4-mini]
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("APPLICATION_YML_PATH", str(REPO_ROOT / "application.local.yml"))
os.environ.setdefault("LLM_CONFIG_PATH", str(REPO_ROOT / "llm_config.local.yml"))
sys.path.insert(0, str(REPO_ROOT / "src"))

from iris.config import settings  # noqa: E402

settings.set_env_vars()

import logging  # noqa: E402

for noisy in ("httpx", "weaviate", "langfuse", "urllib3", "openai", "httpcore"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

from langchain_core.output_parsers import StrOutputParser  # noqa: E402
from langchain_core.prompts import ChatPromptTemplate  # noqa: E402

import iris.domain  # noqa: E402,F401  (must precede iris.llm — circular import)
from iris.llm import CompletionArguments, LlmRequestHandler  # noqa: E402
from iris.llm.langchain import IrisLangchainChatModel  # noqa: E402

JUDGE_SYSTEM = """\
You are a strict evaluator of a university course assistant. The assistant answered a
student question using ONLY the numbered sources shown. Judge the ANSWER, not the
question. Respond with a single JSON object, no markdown fences:

{{"faithfulness": 1-5, "completeness": 1-5, "language_match": true|false,
 "unsupported_claims": ["<claim>", ...],
 "citation_support": [{{"index": <n>, "supports": true|false}}, ...]}}

Scoring:
- faithfulness 5 = every factual claim is directly supported by at least one source;
  3 = mostly supported with minor extrapolation; 1 = substantial unsupported content.
- completeness 5 = uses all sources relevant to the question; 1 = ignores clearly
  relevant sources.
- language_match: true iff the answer is written in the same language as the question.
- citation_support: one entry per numbered source shown; supports=true iff that
  source contains information the answer actually uses."""

JUDGE_USER = """\
QUESTION: {query}

SOURCES (these were cited by the assistant):
{sources}

ANSWER:
{answer}"""


def render_sources(sources: list[dict]) -> str:
    """Mirror the fields the ANSWER model saw (TYPE/COURSE/NAME/CONTENT) — judging
    against less context than the answerer had falsely deflates faithfulness."""
    parts = []
    for i, s in enumerate(sources, 1):
        course = s.get("course") or "this course"
        parts.append(
            f"[{i}] TYPE: {s['type']}\nCOURSE: {course}\n"
            f"NAME: {s['title']}\n"
            f"CONTENT: {s.get('snippet') or '(no snippet)'}"
        )
    return "\n\n".join(parts) or "(none)"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("answers_file", type=Path)
    ap.add_argument("--mode", default="full")
    ap.add_argument("--judge-model", default="personal-openai-gpt-5.4-mini")
    args = ap.parse_args()

    rows = [json.loads(line) for line in open(args.answers_file, encoding="utf-8")]
    answered = [r for r in rows if r["mode"] == args.mode and r["answered"]]
    print(
        f"{len(answered)} answered queries in mode={args.mode} to judge "
        f"with {args.judge_model}"
    )

    llm = IrisLangchainChatModel(
        request_handler=LlmRequestHandler(model_id=args.judge_model),
        completion_args=CompletionArguments(
            response_format="JSON", reasoning_effort="none", max_tokens=800
        ),
    )
    prompt = ChatPromptTemplate.from_messages(
        [("system", JUDGE_SYSTEM), ("user", JUDGE_USER)]
    )
    chain = prompt | llm | StrOutputParser()

    rng = random.Random(42)
    human_sample = set(rng.sample(range(len(answered)), min(30, len(answered))))

    judged = []
    for i, r in enumerate(answered):
        try:
            raw = chain.invoke(
                {
                    "query": r["query"],
                    "sources": render_sources(r["sources"]),
                    "answer": r["answer"],
                }
            )
            cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
            j = json.loads(cleaned)
        except Exception as exc:
            j = {"error": str(exc)[:200]}
        j["query"] = r["query"]
        j["category"] = r["category"]
        j["word_count"] = len(r["answer"].split())
        j["length_ok"] = j["word_count"] <= 300
        j["n_cited"] = len(r["sources"])
        j["human_validation"] = i in human_sample
        judged.append(j)
        f = j.get("faithfulness", "?")
        print(
            f"[{i + 1:3}/{len(answered)}] faith={f} "
            f"comp={j.get('completeness', '?')} [{r['category']}] "
            f"{r['query'][:50]}",
            flush=True,
        )
        time.sleep(0.2)  # gentle rate limiting

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_jsonl = REPO_ROOT / f"eval/results/judge_{args.mode}_{stamp}.jsonl"
    with open(out_jsonl, "w", encoding="utf-8") as f:
        for j in judged:
            f.write(json.dumps(j, ensure_ascii=False) + "\n")

    ok = [j for j in judged if "faithfulness" in j]
    import numpy as np

    lines = [
        f"# Answer-quality judging — mode={args.mode}",
        f"- date: {datetime.now().isoformat(timespec='seconds')}",
        f"- judge model: {args.judge_model} (differs from the answer model)",
        f"- judged: {len(ok)}/{len(judged)} (rest failed to parse)",
    ]
    if ok:
        faith = np.array([j["faithfulness"] for j in ok], dtype=float)
        comp = np.array([j["completeness"] for j in ok], dtype=float)
        lang = sum(bool(j.get("language_match")) for j in ok)
        length = sum(bool(j.get("length_ok")) for j in ok)
        cit_pairs = [c for j in ok for c in j.get("citation_support", [])]
        cit_prec = (
            sum(bool(c.get("supports")) for c in cit_pairs) / len(cit_pairs)
            if cit_pairs
            else 0
        )
        lines += [
            f"- **faithfulness: mean {faith.mean():.2f}** · "
            f"distribution {dict(zip(*np.unique(faith, return_counts=True)))}",
            f"- completeness: mean {comp.mean():.2f}",
            f"- language match: {lang}/{len(ok)}",
            f"- length ≤300 words: {length}/{len(ok)}",
            f"- **citation precision: {cit_prec:.3f}** "
            f"({len(cit_pairs)} cited-source judgements)",
            "",
            "## Lowest-faithfulness answers (manual review priority)",
        ]
        for j in sorted(ok, key=lambda x: x["faithfulness"])[:10]:
            lines.append(
                f"- faith={j['faithfulness']} [{j['category']}] "
                f"{j['query'][:70]} — unsupported: "
                f"{'; '.join(j.get('unsupported_claims', []))[:150]}"
            )
        lines += [
            "",
            f"## Human-validation sample (n={sum(j['human_validation'] for j in judged)})",
            "Score these independently (faithfulness + completeness 1-5), then report",
            "Spearman correlation with the judge as evidence of judge validity.",
        ]
        for j in judged:
            if j["human_validation"]:
                lines.append(f"- [{j['category']}] {j['query']}")
    report = REPO_ROOT / f"eval/results/judge_{args.mode}_{stamp}.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {report}\nDetail: {out_jsonl}")


if __name__ == "__main__":
    main()
