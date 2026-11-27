"""Summarize a study run into one JSON file (points, ranking, timing, cost).

Usage: analyze.py OUT_JSON --labels C2 C3 C1 L4 L1 L2 [--runs runs] [--timing timing]
       [--points judge/points] [--rank-opus judge/ranking-opus] [--rank-argon judge/ranking-argon]
All inputs are relative to $IRIS_STUDY_DATA; missing judge files are skipped.

- Answer score = mean of the five rubric criteria (achieved 100, partly 50, not 0).
- Situation score = mean over repetitions. Overall = mode-weighted mean (programming 89.5 %,
  course 8.6 %, lecture 1.9 %), 95 % bootstrap over situations within modes.
- Ranking: share of rankings in which A was ranked above / equal / below B.
- Timing: warm-up (index 00) dropped; tokens/s = median over calls with >= 200 output tokens.
"""

import argparse
import json
import random
import re
import statistics as st
from collections import defaultdict
from pathlib import Path

from study_paths import DATA, SCENARIOS

WEIGHTS = {
    "PROGRAMMING_EXERCISE_CHAT": 0.895,
    "COURSE_CHAT": 0.086,
    "LECTURE_CHAT": 0.019,
}
POINTS = {"achieved": 100, "partly_achieved": 50, "not_achieved": 0}
MANIFEST = json.loads((SCENARIOS / "manifest.json").read_text(encoding="utf-8"))


def level(sid: str) -> str:
    match = re.search(r"-(low|moderate|high)(-|$)", sid)
    return match.group(1) if match else "other"


def weighted(scores: dict[str, float], sids) -> float:
    by_mode = defaultdict(list)
    for sid in sids:
        by_mode[MANIFEST[sid]["mode"]].append(scores[sid])
    total = sum(WEIGHTS[mode] for mode in by_mode)
    return (
        sum(WEIGHTS[mode] * st.mean(values) for mode, values in by_mode.items()) / total
    )


def bootstrap(values: dict[str, float], draws: int = 4000, seed: int = 11) -> dict:
    sids = sorted(values)
    modes = defaultdict(list)
    for sid in sids:
        modes[MANIFEST[sid]["mode"]].append(sid)
    rng = random.Random(seed)  # nosec B311 - bootstrap resampling, not security
    samples = []
    for _ in range(draws):
        sample = [rng.choice(group) for group in modes.values() for _ in group]
        by_mode = defaultdict(list)
        for sid in sample:
            by_mode[MANIFEST[sid]["mode"]].append(values[sid])
        total = sum(WEIGHTS[mode] for mode in by_mode)
        samples.append(
            sum(WEIGHTS[mode] * st.mean(v) for mode, v in by_mode.items()) / total
        )
    samples.sort()
    return {
        "D": round(weighted(values, sids), 2),
        "lo": round(samples[int(0.025 * draws)], 2),
        "hi": round(samples[int(0.975 * draws)], 2),
        "n": len(sids),
    }


def points(path: Path, runs: str) -> dict:
    per = defaultdict(lambda: defaultdict(list))
    crit = defaultdict(lambda: defaultdict(list))
    leaks = defaultdict(lambda: [0, 0])
    for row in map(json.loads, path.open(encoding="utf-8")):
        match = re.search(rf"{runs}/(\w+)/(.+)__r(\d+)\.json$", row["path"])
        if not match:
            continue
        label, sid = match.group(1), match.group(2)
        per[label][sid].append(st.mean(POINTS[v] for v in row["ratings"].values()))
        for key, value in row["ratings"].items():
            crit[label][key].append(POINTS[value])
        leaks[label][1] += 1
        leaks[label][0] += any(
            error.get("present") and "solution" in error.get("description", "")
            for error in row["criticalErrors"]
        )
    situation = {
        label: {sid: st.mean(v) for sid, v in d.items()} for label, d in per.items()
    }
    result: dict = {"abs": {}, "diff": {}}
    for label, values in situation.items():
        boot = bootstrap(values)
        result["abs"][label] = {
            "mean": round(boot["D"], 1),
            "lo": round(boot["lo"], 1),
            "hi": round(boot["hi"], 1),
        }
    result["overall"] = {label: value["mean"] for label, value in result["abs"].items()}
    for first in situation:
        for second in situation:
            if first != second:
                common = set(situation[first]) & set(situation[second])
                result["diff"][f"{first}-{second}"] = bootstrap(
                    {
                        sid: situation[first][sid] - situation[second][sid]
                        for sid in common
                    }
                )
    result["criteria"] = {
        label: {k: round(st.mean(v)) for k, v in d.items()} for label, d in crit.items()
    }
    result["leaks"] = {label: f"{v[0]}/{v[1]}" for label, v in leaks.items()}
    return result


def ranking(path: Path, labels: list[str]) -> dict:
    rows = [json.loads(line) for line in path.open(encoding="utf-8")]
    count = len(rows)
    result: dict = {
        "n": count,
        "mean": {m: round(st.mean(r["ranks"][m] for r in rows), 2) for m in labels},
        "pairs": {},
        "byLevel": {},
    }
    for first in labels:
        for second in labels:
            if first == second:
                continue
            better = round(
                100 * sum(r["ranks"][first] < r["ranks"][second] for r in rows) / count
            )
            tie = round(
                100 * sum(r["ranks"][first] == r["ranks"][second] for r in rows) / count
            )
            result["pairs"][f"{first}-{second}"] = {
                "better": better,
                "tie": tie,
                "worse": 100 - better - tie,
            }
    for name in ("low", "moderate", "high"):
        subset = [r for r in rows if level(r["sid"]) == name]
        if subset:
            result["byLevel"][name] = {
                f"{a}-{b}": round(
                    100
                    * sum(r["ranks"][a] < r["ranks"][b] for r in subset)
                    / len(subset)
                )
                for a in labels
                for b in labels
                if a != b
            }
    return result


def telemetry_calls(result: dict) -> list[dict]:
    # Older runs kept the call list in the diagnostics (which the judge saw).
    return (result.get("telemetry") or {}).get("modelCalls") or result.get(
        "diagnostics", {}
    ).get("modelCalls", [])


def timing(folder: Path, labels: list[str]) -> dict:
    out = {}
    for label in labels:
        directory = folder / label
        if not directory.exists():
            continue
        rows = [
            json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(directory.glob("*.json"))
        ]
        rows = [
            r
            for p, r in zip(sorted(directory.glob("*.json")), rows)
            if not p.name.startswith("00-")
        ]
        ok = [r for r in rows if not r.get("executionError")]
        answer = sorted(
            r["timing"]["answerSeconds"]
            for r in ok
            if r.get("timing", {}).get("answerSeconds")
        )
        first = sorted(
            r["timing"]["firstTextSeconds"]
            for r in ok
            if r.get("timing", {}).get("firstTextSeconds")
        )
        calls = [
            c
            for r in ok
            for c in telemetry_calls(r)
            if (c.get("outputTokens") or 0) >= 200 and c.get("seconds")
        ]
        outputs = [
            sum(c.get("outputTokens") or 0 for c in telemetry_calls(r)) for r in ok
        ]
        out[label] = {
            "n": len(rows),
            "errors": len(rows) - len(ok),
            "raw": answer,
            "firstRaw": first,
            "answerMedian": round(st.median(answer), 1) if answer else None,
            "mean": round(st.mean(answer), 1) if answer else None,
            "firstMedian": round(st.median(first), 1) if first else None,
            "tps": (
                round(st.median(c["outputTokens"] / c["seconds"] for c in calls))
                if calls
                else None
            ),
            "tpsN": len(calls),
            "outMedian": round(st.median(outputs)) if outputs else None,
        }
    return out


def cost(folder: Path, labels: list[str]) -> dict:
    out = {}
    for label in labels:
        rows = [
            json.loads(p.read_text(encoding="utf-8"))
            for p in (folder / label).glob("*.json")
        ]
        totals = [
            sum(u["costUsd"] for u in r.get("usage", []))
            for r in rows
            if not r.get("executionError")
        ]
        if totals and any(totals):
            out[label] = round(1000 * st.mean(totals), 2)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    parser.add_argument("--labels", nargs="+", required=True)
    parser.add_argument("--runs", default="runs")
    parser.add_argument("--timing", default="timing")
    parser.add_argument("--points", default="judge/points")
    parser.add_argument("--rank-opus", default="judge/ranking-opus")
    parser.add_argument("--rank-argon", default="judge/ranking-argon")
    args = parser.parse_args()
    result: dict = {
        "timing": timing(DATA / args.timing, args.labels),
        "costPer1000PyrisPrices": cost(DATA / args.runs, args.labels),
        "rank": {},
    }
    points_file = DATA / f"{args.points}.jsonl"
    if points_file.exists():
        result["points"] = points(points_file, args.runs)
    for judge, name in (("opus", args.rank_opus), ("argon", args.rank_argon)):
        path = DATA / f"{name}.jsonl"
        if path.exists():
            result["rank"][judge] = ranking(path, args.labels)
    Path(args.out).write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(
        json.dumps(
            {
                "overall": result.get("points", {}).get("overall"),
                "cost": result["costPer1000PyrisPrices"],
            }
        )
    )


if __name__ == "__main__":
    main()
