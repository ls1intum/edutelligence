#!/usr/bin/env python3
"""
Evaluation script for variant tests. Purpose is
to iterate through all the variants and calculate the
accuracy aka F1 Value for each test, combine it with
input token size and save in a dictionary, grouped by
model type.

Plot the result in a graph and calculate Pearson
correlation between input token size and F1 Value.
"""

import os
import json
from pathlib import Path
import re

from collections import defaultdict
from typing import Dict, List, Tuple, Set


def get_run_id_from_filename(filename) -> str | None:
    """Extract run ID from filename.
    '20250727_091546_65d45dbb_result.json' -> '65d45dbb'
    """
    match = re.search(r"_(\w+)_result\.json$", filename)
    if match:
        return match.group(1)
    else:
        return None


def get_stats_file_with_run_id(result_file_path, run_id) -> str | None:
    """
    Get the corresponding stats file for a given result
    file and run ID.
    """
    dir = os.path.dirname(result_file_path)
    expected_stat_file = f"{run_id}_stats.json"

    for file in os.listdir(dir):
        if file.endswith(expected_stat_file):
            stats_file_path = os.path.join(dir, file)
            return stats_file_path
    return None


# ------------FROM CREATE_EVALUATION_REPORT.PY-----------------


def unify_model_name(model_name: str) -> str:
    """Normalise provider-qualified model identifiers.

    The input model_name may contain provider prefixes and preview suffixes,
    e.g. "openrouter:google/gemini-2.5-flash-lite-preview-06-17". We return
    a concise key by stripping the provider, selecting the last path
    component, and collapsing Gemini Flash Lite preview versions into a
    single key (``gemini-2.5-flash-lite``).
    """
    if ":" in model_name:
        spec = model_name.split(":", 1)[1]
    else:
        spec = model_name
    short = spec.split("/")[-1]
    # normalise Flash Lite preview identifiers
    if "flash-lite" in short:
        return "gemini-2.5-flash-lite"
    return short


def unify_path(path: str) -> str:
    """Canonicalise file paths by removing repository prefixes.

    Gold annotations store paths relative to the repository root (e.g.
    ``src/com/example/Foo.java``) whereas predictions sometimes prefix
    ``solution_repository/`` or ``template_repository/``. To enable
    matching, we strip these known prefixes. Empty file paths (used for
    problem statements) are normalised to ``problem_statement.md``.
    """
    if not path:
        return ""
    for prefix in ["solution_repository/", "template_repository/"]:
        if path.startswith(prefix):
            return path[len(prefix) :]
    return path


def issue_to_tokens(issue: Dict) -> Set[Tuple[str, str, int]]:
    """Transform an issue into a set of tokens for overlap calculation.

    Each issue contains one or more ``related_locations`` specifying the
    artifact type, file path, and line range. We convert each line in
    each location into a token ``(artifact_type, file_path, line)``. The
    file path is canonicalised via :func:`unify_path`. For empty file
    paths, we use a placeholder ``problem_statement.md``. The tokens
    uniquely identify each affected line and allow straightforward
    computation of set overlap.
    """
    tokens: Set[Tuple[str, str, int]] = set()
    for loc in issue.get("related_locations", []):
        art_type = loc.get("type")
        file_path = unify_path(loc.get("file_path") or "")
        if not file_path:
            file_path = "problem_statement.md"
        start = int(loc.get("start_line", 0))
        end = int(loc.get("end_line", start))
        for line in range(start, end + 1):
            tokens.add((art_type, file_path, line))
    return tokens


def compute_f1_iou(
    pred_tokens: Set[Tuple[str, str, int]], gold_tokens: Set[Tuple[str, str, int]]
) -> Tuple[float, float]:
    """Compute Dice/F1 and IoU between two sets of tokens.

    The Dice coefficient (F1) is defined as ``2|A∩B| / (|A| + |B|)``.
    The Intersection‑over‑Union (IoU) is ``|A∩B| / |A∪B|``.
    Both return zero if either set is empty or if there is no overlap.
    """
    if not pred_tokens or not gold_tokens:
        return 0.0, 0.0
    intersection = pred_tokens & gold_tokens  # TRUE POSITIVES
    if not intersection:
        return 0.0, 0.0
    inter = len(intersection)
    precision = inter / len(
        pred_tokens
    )  # TRUE POSITIVES / (TRUE POSITIVES + FALSE POSITIVES)
    recall = inter / len(
        gold_tokens
    )  # TRUE POSITIVES / (TRUE POSITIVES + FALSE NEGATIVES)
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    union = len(pred_tokens | gold_tokens)
    iou = inter / union if union > 0 else 0.0
    return f1, iou


def greedy_match(
    pred_issues: List[Dict], gold_issues: List[Dict]
) -> Tuple[List[Tuple[int, int, float, float]], Set[int], Set[int]]:
    """Greedily match predicted issues to gold issues within each category.

    We generate candidate pairs for issues of the same category and compute
    their span F1 and IoU. Candidate pairs with zero F1 are discarded. We
    then sort candidates by descending F1 and IoU and iteratively select
    matches, ensuring each predicted and gold issue is used at most once.
    The function returns the list of selected matches and the sets of matched indices.
    """
    candidates: List[Tuple[float, float, int, int]] = []
    for i, p in enumerate(pred_issues):
        for j, g in enumerate(gold_issues):
            if p["category"] != g["category"]:
                continue
            f1, iou = compute_f1_iou(p["tokens"], g["tokens"])
            if f1 > 0:
                candidates.append((f1, iou, i, j))
    candidates.sort(key=lambda x: (-x[0], -x[1]))
    matched_pred: Set[int] = set()
    matched_gold: Set[int] = set()
    matches: List[Tuple[int, int, float, float]] = []
    for f1, iou, i, j in candidates:
        if i not in matched_pred and j not in matched_gold:
            matched_pred.add(i)
            matched_gold.add(j)
            matches.append((i, j, f1, iou))
    return matches, matched_pred, matched_gold


def process_variant(gt_path: str, pred_path: str) -> Tuple[List[Dict], List[Dict]]:
    """Load and prepare gold and predicted issues for a single variant run."""
    gold = json.load(open(gt_path, "r", encoding="utf-8"))
    gold_issues = []
    for issue in gold.get("issues", []):
        tokens = issue_to_tokens(issue)
        gold_issues.append(
            {"category": issue["category"], "tokens": tokens, "raw": issue}
        )
    pred = json.load(open(pred_path, "r", encoding="utf-8"))
    response = pred.get("response", {})
    pred_issues = []
    for issue in response.get("issues", []):
        tokens = issue_to_tokens(issue)
        pred_issues.append(
            {"category": issue.get("category"), "tokens": tokens, "raw": issue}
        )
    return gold_issues, pred_issues


def evaluate_run(gold_issues: List[Dict], pred_issues: List[Dict]) -> Tuple[
    int,
    int,
    int,
    List[Tuple[int, int, float, float]],
    Dict[str, Tuple[int, int, int, float, float, int]],
]:
    """Evaluate a single model run on one variant.

    Returns overall TP, FP, FN counts, the list of matches, and per‑category
    statistics capturing TP, FP, FN and sums of span F1 and IoU.
    """
    matches, matched_pred, matched_gold = greedy_match(pred_issues, gold_issues)
    tp = len(matches)
    fp = len(pred_issues) - tp
    fn = len(gold_issues) - tp
    per_cat: Dict[str, List] = defaultdict(lambda: [0, 0, 0, 0.0, 0.0, 0])
    for pred_idx, _, f1, iou in matches:
        cat = pred_issues[pred_idx]["category"]
        stats = per_cat[cat]
        stats[0] += 1  # TP
        stats[3] += f1
        stats[4] += iou
        stats[5] += 1
    for i, p in enumerate(pred_issues):
        if i not in matched_pred:
            stats = per_cat[p["category"]]
            stats[1] += 1  # FP
    for j, g in enumerate(gold_issues):
        if j not in matched_gold:
            stats = per_cat[g["category"]]
            stats[2] += 1  # FN
    return tp, fp, fn, matches, per_cat


# ---------------------------------------------------


def iterate_test_files(data_dir: str = "data") -> None:
    """
    Iterate through all variant/{}/outputs files and extract required information
    """
    if not os.path.isdir(data_dir):
        raise ValueError(
            f"Data directory {data_dir} does not exist or is not a directory."
        )

    total_analysed_files = 0

    results_by_model = defaultdict(list)

    for course in sorted(os.listdir(data_dir)):
        course_dir = os.path.join(data_dir, course)
        if not os.path.isdir(course_dir):
            continue

        # print(f"\n=== Processing Course: {course} ===")

        for exercise in sorted(os.listdir(course_dir)):
            exercise_dir = os.path.join(course_dir, exercise)
            if not os.path.isdir(exercise_dir):
                continue

            variants_dir = os.path.join(exercise_dir, "variants")
            if not os.path.isdir(variants_dir):
                continue

            for variant in sorted(os.listdir(variants_dir)):
                variant_dir = os.path.join(variants_dir, variant)
                if not os.path.isdir(variant_dir):
                    continue
                outputs_dir = os.path.join(variant_dir, "outputs")
                if not os.path.isdir(outputs_dir):
                    continue

                # print(f"\nVariant: {variant}")
                # Load gold standard for this variant
                gold_standard_path = os.path.join(variant_dir, f"{variant}.json")
                if not os.path.isfile(gold_standard_path):
                    print(
                        f"Warning: Gold standard file not found: {gold_standard_path}"
                    )
                    continue

                result_files = [
                    file
                    for file in os.listdir(outputs_dir)
                    if file.endswith("_result.json")
                ]
                for result_file in sorted(result_files):
                    result_file_path = os.path.join(outputs_dir, result_file)

                    run_id = get_run_id_from_filename(result_file)
                    if not run_id:
                        print(f"Warning: Could not extract run ID from {result_file}")
                        continue

                    stats_file_path = get_stats_file_with_run_id(
                        result_file_path, run_id
                    )
                    try:
                        with open(result_file_path, "r", encoding="utf-8") as file:
                            result_data = json.load(file)

                        model_name = result_data.get("model_name", "unknown_model")
                        unified_model_name = unify_model_name(model_name)
                        issues = result_data.get("response", {}).get("issues", [])
                        num_issues = len(issues)

                        prompt_tokens = None
                        if stats_file_path and os.path.isfile(stats_file_path):
                            try:
                                with open(
                                    stats_file_path, "r", encoding="utf-8"
                                ) as file:
                                    stats_data = json.load(file)
                                prompt_tokens = stats_data.get("prompt_tokens", "N/A")
                            except Exception as e:
                                print(
                                    f"Warning: Could not read stats file {stats_file_path}: {e}"
                                )
                        # --------------
                        try:
                            gold_issues, pred_issues = process_variant(
                                gold_standard_path, result_file_path
                            )
                            tp, fp, fn, matches, _ = evaluate_run(
                                gold_issues, pred_issues
                            )

                            # Calculate F1 for this individual run
                            precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
                            recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
                            f1 = (
                                2 * precision * recall / (precision + recall)
                                if (precision + recall) > 0
                                else 0.0
                            )

                            # if matches:
                            #     avg_iou = sum(iou for _, _, _, iou in matches) / len(matches)
                            # else:
                            #     avg_iou = 0.0

                            # Store data for this run
                            run_data = {
                                "variant": variant,
                                "course": course,
                                "exercise": exercise,
                                "prompt_tokens": prompt_tokens,
                                "f1": f1,
                                "precision": precision,
                                "recall": recall,
                                #'iou': avg_iou,
                                "tp": tp,
                                "fp": fp,
                                "fn": fn,
                                "issues_found": num_issues,
                            }
                            results_by_model[unified_model_name].append(run_data)
                            # print(f"File: {result_file}")
                            # print(f"Model: {unified_model_name} (original: {model_name})")
                            # print(f"Issues found: {num_issues}")
                            # print(f"Prompt tokens: {prompt_tokens}")
                            # print(f"TP: {tp}, FP: {fp}, FN: {fn}")
                            # print(f"Precision: {precision:.3f}, Recall: {recall:.3f}, F1: {f1:.3f}")
                            # if issues:
                            #     print(f"      Issue categories: {[issue.get('category', 'unknown') for issue in issues]}")
                            total_analysed_files += 1
                        except Exception as e:
                            print(f"Error comparing with gold standard: {e}")
                            print(f"File: {result_file}")
                            # print(f"Model: {unified_model_name} (original: {model_name})")
                            # print(f"Issues found: {num_issues}")
                            # print(f"Prompt tokens: {prompt_tokens}")
                        # --------------
                    except Exception as e:
                        print(
                            f"Warning: Could not read result file {result_file_path}: {e}"
                        )

    output_file = "model_performance_results.json"

    with open(output_file, "w", encoding="utf-8") as file:
        json.dump(results_by_model, file, indent=2)

    print(f"\n=== Summary ===")
    print(f"Total result files processed: {total_analysed_files}")


if __name__ == "__main__":
    iterate_test_files(data_dir="../data")
