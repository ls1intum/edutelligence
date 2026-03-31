"""
Analyze top-k classification results for a workload CSV.

Example:
    docker exec -i logos-server python tests/performance/analyze_workload_classification.py \
        --workload tests/performance/workloads/workload_resource_mode_local5_bursty_60_1h.csv \
        --allowed-model Qwen/Qwen2.5-Coder-7B-Instruct-AWQ \
        --allowed-model Qwen/Qwen2.5-Coder-14B-Instruct-AWQ \
        --allowed-model Qwen/Qwen2.5-7B-Instruct-AWQ \
        --allowed-model Qwen/Qwen2.5-14B-Instruct-AWQ \
        --allowed-model casperhansen/deepseek-r1-distill-llama-8b-awq \
        --allowed-model gpt-4.1-mini \
        --allowed-model gpt-4.1
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from logos.classification.classification_balancer import Balancer
from logos.classification.classification_manager import ClassificationManager
from logos.classification.proxy_policy import ProxyPolicy
from logos.dbutils.dbmanager import DBManager


def parse_workload(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("Workload CSV is missing a header row.")
        for row in reader:
            body_json = row.get("body_json")
            if not body_json:
                raise ValueError(f"Missing body_json for row: {row}")
            rows.append(
                {
                    "request_id": row.get("request_id") or "",
                    "body_json": body_json,
                }
            )
    return rows


def build_classifier() -> tuple[ClassificationManager, dict[str, int]]:
    models: list[dict] = []
    name_to_id: dict[str, int] = {}
    with DBManager() as db:
        for model_id in db.get_all_models():
            tpl = db.get_model(model_id)
            if tpl is None:
                continue
            models.append(
                {
                    "id": tpl["id"],
                    "name": tpl["name"],
                    "weight_privacy": tpl["weight_privacy"],
                    "weight_latency": tpl["weight_latency"],
                    "weight_accuracy": tpl["weight_accuracy"],
                    "weight_cost": tpl["weight_cost"],
                    "weight_quality": tpl["weight_quality"],
                    "tags": tpl["tags"],
                    "parallel": tpl["parallel"],
                    "description": tpl["description"],
                    "classification_weight": Balancer(),
                }
            )
            name_to_id[tpl["name"]] = tpl["id"]

    classifier = ClassificationManager(models)
    classifier.update_manager(models)
    return classifier, name_to_id


def extract_prompts(payload: dict) -> tuple[str, str]:
    messages = payload.get("messages", [])
    user_prompt = ""
    system_prompt = ""
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role", "")).lower()
        content = message.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        if role == "user":
            user_prompt = str(content)
        elif role == "system":
            system_prompt = str(content)
    return user_prompt, system_prompt


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze workload classification spread.")
    parser.add_argument("--workload", required=True, help="Path to workload CSV.")
    parser.add_argument(
        "--allowed-model",
        action="append",
        default=[],
        help="Restrict classification to these model names. Repeat for multiple models.",
    )
    parser.add_argument("--top-k", type=int, default=3, help="How many ranked models to print per row.")
    parser.add_argument("--show-rows", action="store_true", help="Print per-request top-k results.")
    args = parser.parse_args()

    workload = parse_workload(Path(args.workload))
    classifier, name_to_id = build_classifier()
    allowed_ids = None
    if args.allowed_model:
        missing = [name for name in args.allowed_model if name not in name_to_id]
        if missing:
            raise SystemExit(f"Unknown model(s): {', '.join(missing)}")
        allowed_ids = [name_to_id[name] for name in args.allowed_model]

    policy = ProxyPolicy()
    counts: Counter[str] = Counter()

    for row in workload:
        payload = json.loads(row["body_json"])
        user_prompt, system_prompt = extract_prompts(payload)
        ranked = classifier.classify(
            user_prompt,
            policy,
            allowed=allowed_ids,
            system=system_prompt,
        )
        if not ranked:
            raise SystemExit(f"No classification candidates for request {row['request_id']}")
        top_names = []
        for model_id, weight, *_ in ranked[: args.top_k]:
            model_name = next(name for name, resolved_id in name_to_id.items() if resolved_id == model_id)
            top_names.append(f"{model_name} ({weight:.3f})")
        winner = top_names[0].split(" (", 1)[0]
        counts[winner] += 1
        if args.show_rows:
            print(f"{row['request_id']}: " + " | ".join(top_names))

    print("Top-1 Counts")
    for model_name, count in counts.most_common():
        print(f"{model_name}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
