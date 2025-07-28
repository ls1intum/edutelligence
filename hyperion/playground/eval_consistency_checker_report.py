#!/usr/bin/env python3
"""
Extended evaluation script for the programming exercise consistency detector.

This script evaluates model predictions against human gold annotations for
programming exercise variants. It computes detection and localisation
metrics using a greedy span matching protocol. In addition to the
standard metrics (precision, recall, F1, span F1, IoU, runtime and cost),
the extended version also summarises the dataset composition: how many
annotated variants are present per exercise, the total number of
annotated issues, and how those issues are distributed across the six
inconsistency categories and three artifact types. This facilitates
transparency about the benchmark and helps contextualise the reported
performance metrics.

Usage:
    python eval_consistency_checker_report.py

The script automatically scans the data/ directory for courses (like ITP2425) and their exercises.
The output JSON will be saved as 'consistency_evaluation_results.json' in the current directory.

The evaluation approach follows the standard protocol used in event
mention detection: for each variant, predicted issues are greedily
matched to gold issues of the same category to maximise the overall
Dice/F1 overlap between their line spans. Each gold and
predicted issue is used at most once in the matching. Span
overlap quality is measured by the Dice (F1) coefficient and the
Intersection‑over‑Union (IoU) metric.
"""

import json
import os
from collections import defaultdict, Counter
from typing import Dict, List, Tuple, Set


def unify_model_name(model_name: str) -> str:
    """Normalise provider-qualified model identifiers.

    The input model_name may contain provider prefixes and preview suffixes,
    e.g. "openrouter:google/gemini-2.5-flash-lite-preview-06-17". We return
    a concise key by stripping the provider, selecting the last path
    component, and collapsing Gemini Flash Lite preview versions into a
    single key (``gemini-2.5-flash-lite``).
    """
    if ':' in model_name:
        spec = model_name.split(':', 1)[1]
    else:
        spec = model_name
    short = spec.split('/')[-1]
    # normalise Flash Lite preview identifiers
    if 'flash-lite' in short:
        return 'gemini-2.5-flash-lite'
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
        return ''
    for prefix in ['solution_repository/', 'template_repository/']:
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
    for loc in issue.get('related_locations', []):
        art_type = loc.get('type')
        file_path = unify_path(loc.get('file_path') or '')
        if not file_path:
            file_path = 'problem_statement.md'
        start = int(loc.get('start_line', 0))
        end = int(loc.get('end_line', start))
        for line in range(start, end + 1):
            tokens.add((art_type, file_path, line))
    return tokens


def compute_f1_iou(pred_tokens: Set[Tuple[str, str, int]],
                   gold_tokens: Set[Tuple[str, str, int]]) -> Tuple[float, float]:
    """Compute Dice/F1 and IoU between two sets of tokens.

    The Dice coefficient (F1) is defined as ``2|A∩B| / (|A| + |B|)``.
    The Intersection‑over‑Union (IoU) is ``|A∩B| / |A∪B|``.
    Both return zero if either set is empty or if there is no overlap.
    """
    if not pred_tokens or not gold_tokens:
        return 0.0, 0.0
    intersection = pred_tokens & gold_tokens
    if not intersection:
        return 0.0, 0.0
    inter = len(intersection)
    precision = inter / len(pred_tokens)
    recall = inter / len(gold_tokens)
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    union = len(pred_tokens | gold_tokens)
    iou = inter / union if union > 0 else 0.0
    return f1, iou


def greedy_match(pred_issues: List[Dict], gold_issues: List[Dict]) -> Tuple[List[Tuple[int, int, float, float]], Set[int], Set[int]]:
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
            if p['category'] != g['category']:
                continue
            f1, iou = compute_f1_iou(p['tokens'], g['tokens'])
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
    gold = json.load(open(gt_path, 'r', encoding='utf-8'))
    gold_issues = []
    for issue in gold.get('issues', []):
        tokens = issue_to_tokens(issue)
        gold_issues.append({'category': issue['category'], 'tokens': tokens, 'raw': issue})
    pred = json.load(open(pred_path, 'r', encoding='utf-8'))
    response = pred.get('response', {})
    pred_issues = []
    for issue in response.get('issues', []):
        tokens = issue_to_tokens(issue)
        pred_issues.append({'category': issue.get('category'), 'tokens': tokens, 'raw': issue})
    return gold_issues, pred_issues


def evaluate_run(gold_issues: List[Dict], pred_issues: List[Dict]) -> Tuple[int, int, int, List[Tuple[int, int, float, float]], Dict[str, Tuple[int, int, int, float, float, int]]]:
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
        cat = pred_issues[pred_idx]['category']
        stats = per_cat[cat]
        stats[0] += 1  # TP
        stats[3] += f1
        stats[4] += iou
        stats[5] += 1
    for i, p in enumerate(pred_issues):
        if i not in matched_pred:
            stats = per_cat[p['category']]
            stats[1] += 1  # FP
    for j, g in enumerate(gold_issues):
        if j not in matched_gold:
            stats = per_cat[g['category']]
            stats[2] += 1  # FN
    return tp, fp, fn, matches, per_cat


def accumulate(aggregates: Dict, model_key: str, exercise: str,
               tp: int, fp: int, fn: int, matches: List[Tuple[int, int, float, float]],
               per_cat: Dict[str, Tuple[int, int, int, float, float, int]],
               duration: float, cost: float) -> None:
    """Accumulate run statistics into nested aggregators."""
    m = aggregates.setdefault(model_key, {
        'TP': 0, 'FP': 0, 'FN': 0,
        'sum_span_f1': 0.0, 'sum_iou': 0.0, 'n_matched': 0,
        'runs': 0, 'runtimes': [], 'costs': [],
        'per_exercise': {}, 'per_category': {}
    })
    m['TP'] += tp; m['FP'] += fp; m['FN'] += fn; m['runs'] += 1
    m['runtimes'].append(duration); m['costs'].append(cost)
    for _, _, f1, iou in matches:
        m['sum_span_f1'] += f1; m['sum_iou'] += iou; m['n_matched'] += 1
    # per exercise
    ex = m['per_exercise'].setdefault(exercise, {
        'TP': 0, 'FP': 0, 'FN': 0,
        'sum_span_f1': 0.0, 'sum_iou': 0.0, 'n_matched': 0,
        'runs': 0, 'runtimes': [], 'costs': []
    })
    ex['TP'] += tp; ex['FP'] += fp; ex['FN'] += fn; ex['runs'] += 1
    ex['runtimes'].append(duration); ex['costs'].append(cost)
    for _, _, f1, iou in matches:
        ex['sum_span_f1'] += f1; ex['sum_iou'] += iou; ex['n_matched'] += 1
    # per category
    for cat, (cat_tp, cat_fp, cat_fn, cat_sum_f1, cat_sum_iou, cat_n) in per_cat.items():
        cs = m['per_category'].setdefault(cat, {'TP': 0, 'FP': 0, 'FN': 0,
                                               'sum_span_f1': 0.0, 'sum_iou': 0.0,
                                               'n_matched': 0})
        cs['TP'] += cat_tp; cs['FP'] += cat_fp; cs['FN'] += cat_fn
        cs['sum_span_f1'] += cat_sum_f1; cs['sum_iou'] += cat_sum_iou; cs['n_matched'] += cat_n


def finalise(aggregates: Dict) -> Dict[str, Dict]:
    """Compute precision, recall, F1 and average span metrics from aggregates."""
    results: Dict[str, Dict] = {}
    for model_key, m in aggregates.items():
        res = {}
        tp, fp, fn = m['TP'], m['FP'], m['FN']
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        span_f1 = m['sum_span_f1'] / m['n_matched'] if m['n_matched'] > 0 else 0.0
        iou = m['sum_iou'] / m['n_matched'] if m['n_matched'] > 0 else 0.0
        avg_time = sum(m['runtimes']) / len(m['runtimes']) if m['runtimes'] else 0.0
        avg_cost = sum(m['costs']) / len(m['costs']) if m['costs'] else 0.0
        res.update({
            'TP': tp, 'FP': fp, 'FN': fn,
            'precision': precision, 'recall': recall, 'F1': f1,
            'span_F1': span_f1, 'IoU': iou,
            'avg_time_s': avg_time, 'avg_cost': avg_cost,
            'runs': m['runs']
        })
        # per exercise
        per_ex = {}
        for ex_name, ex in m['per_exercise'].items():
            tp_e, fp_e, fn_e = ex['TP'], ex['FP'], ex['FN']
            prec_e = tp_e / (tp_e + fp_e) if (tp_e + fp_e) > 0 else 0.0
            rec_e = tp_e / (tp_e + fn_e) if (tp_e + fn_e) > 0 else 0.0
            f1_e = 2 * prec_e * rec_e / (prec_e + rec_e) if (prec_e + rec_e) > 0 else 0.0
            span_f1_e = ex['sum_span_f1'] / ex['n_matched'] if ex['n_matched'] > 0 else 0.0
            iou_e = ex['sum_iou'] / ex['n_matched'] if ex['n_matched'] > 0 else 0.0
            avg_t = sum(ex['runtimes']) / len(ex['runtimes']) if ex['runtimes'] else 0.0
            avg_c = sum(ex['costs']) / len(ex['costs']) if ex['costs'] else 0.0
            per_ex[ex_name] = {
                'TP': tp_e, 'FP': fp_e, 'FN': fn_e,
                'precision': prec_e, 'recall': rec_e, 'F1': f1_e,
                'span_F1': span_f1_e, 'IoU': iou_e,
                'avg_time_s': avg_t, 'avg_cost': avg_c, 'runs': ex['runs']
            }
        res['per_exercise'] = per_ex
        # per category
        per_cat_res = {}
        for cat, c in m['per_category'].items():
            tp_c, fp_c, fn_c = c['TP'], c['FP'], c['FN']
            prec_c = tp_c / (tp_c + fp_c) if (tp_c + fp_c) > 0 else 0.0
            rec_c = tp_c / (tp_c + fn_c) if (tp_c + fn_c) > 0 else 0.0
            f1_c = 2 * prec_c * rec_c / (prec_c + rec_c) if (prec_c + rec_c) > 0 else 0.0
            span_f1_c = c['sum_span_f1'] / c['n_matched'] if c['n_matched'] > 0 else 0.0
            iou_c = c['sum_iou'] / c['n_matched'] if c['n_matched'] > 0 else 0.0
            per_cat_res[cat] = {
                'TP': tp_c, 'FP': fp_c, 'FN': fn_c,
                'precision': prec_c, 'recall': rec_c, 'F1': f1_c,
                'span_F1': span_f1_c, 'IoU': iou_c
            }
        res['per_category'] = per_cat_res
        results[model_key] = res
    return results


def summarise_dataset(data_dir: str, included_exercises: set = None) -> Dict:
    """Generate a summary of the annotated benchmark for transparency.

    The summary reports the number of annotated variants per course and exercise, the
    total number of gold issues, how many issues fall into each category,
    and how many issues involve each artifact type. Issues may reference
    multiple artifacts, so artifact counts are not mutually exclusive.
    """
    course_counts: Dict[str, Dict[str, int]] = {}
    ex_counts: Dict[str, int] = {}
    cat_counts: Counter = Counter()
    artefact_counts: Counter = Counter()
    total_variants = 0
    total_issues = 0
    
    for course in sorted(os.listdir(data_dir)):
        course_dir = os.path.join(data_dir, course)
        if not os.path.isdir(course_dir):
            continue
            
        course_counts[course] = {}
        
        for ex in sorted(os.listdir(course_dir)):
            # Skip exercises not in our included list
            if included_exercises and ex not in included_exercises:
                continue
                
            var_dir = os.path.join(course_dir, ex, 'variants')
            if not os.path.isdir(var_dir):
                continue
                
            ex_key = f"{course}/{ex}"
            
            for v in os.listdir(var_dir):
                gt = os.path.join(var_dir, v, f'{v}.json')
                if os.path.isfile(gt):
                    total_variants += 1
                    ex_counts[ex_key] = ex_counts.get(ex_key, 0) + 1
                    course_counts[course][ex] = course_counts[course].get(ex, 0) + 1
                    
                    data = json.load(open(gt, 'r'))
                    issues = data.get('issues', [])
                    total_issues += len(issues)
                    for issue in issues:
                        cat_counts[issue['category']] += 1
                        types = {loc['type'] for loc in issue.get('related_locations', [])}
                        for t in types:
                            artefact_counts[t] += 1
                            
    return {
        'variants_per_course': course_counts,
        'variants_per_exercise': ex_counts,
        'total_annotated_variants': total_variants,
        'total_issues': total_issues,
        'issues_per_category': dict(cat_counts),
        'issues_per_artifact': {k: v for k, v in artefact_counts.items()}
    }


def main():
    data_dir = 'data'
    output_json = 'consistency_evaluation_results.json'
    
    # Only include these specific exercises
    included_exercises = {
        'H01E01-Lectures',
        'H02E02-Panic_at_Seal_Saloon', 
        'H05E01-Space_Seal_Farm'
    }
    
    if not os.path.isdir(data_dir):
        print(f"Error: Data directory '{data_dir}' not found!")
        return
    
    aggregates: Dict = {}
    
    # dataset summary
    ds_summary = summarise_dataset(data_dir, included_exercises)
    
    # iterate courses, exercises, variants and runs
    for course in sorted(os.listdir(data_dir)):
        course_dir = os.path.join(data_dir, course)
        if not os.path.isdir(course_dir):
            continue
            
        print(f"Processing course: {course}")
        
        for ex in sorted(os.listdir(course_dir)):
            # Skip exercises not in our included list
            if ex not in included_exercises:
                continue
                
            var_dir = os.path.join(course_dir, ex, 'variants')
            if not os.path.isdir(var_dir):
                continue
            
            ex_key = f"{course}/{ex}"
            
            for v in sorted(os.listdir(var_dir)):
                gt_path = os.path.join(var_dir, v, f'{v}.json')
                if not os.path.isfile(gt_path):
                    continue
                
                outputs = os.path.join(var_dir, v, 'outputs')
                if not os.path.isdir(outputs):
                    print(f"Warning: No outputs directory found for {ex_key}/variants/{v}")
                    continue
                    
                for fname in os.listdir(outputs):
                    if not fname.endswith('_result.json'):
                        continue
                        
                    result_path = os.path.join(outputs, fname)
                    stats_path = result_path.replace('_result.json', '_stats.json')
                    
                    try:
                        gold_issues, pred_issues = process_variant(gt_path, result_path)
                        tp, fp, fn, matches, per_cat = evaluate_run(gold_issues, pred_issues)
                    except Exception as e:
                        print(f"Error processing {result_path}: {e}")
                        continue
                    
                    duration = 0.0; cost = 0.0
                    if os.path.isfile(stats_path):
                        try:
                            stats = json.load(open(stats_path, 'r'))
                            duration = float(stats.get('duration', 0.0))
                            cost = float(stats.get('total_cost', 0.0))
                        except Exception:
                            pass
                    
                    try:
                        res_json = json.load(open(result_path, 'r'))
                        model_name = res_json.get('model_name') or res_json.get('model', 'unknown')
                    except Exception:
                        model_name = 'unknown'
                    
                    model_key = unify_model_name(model_name)
                    accumulate(aggregates, model_key, ex_key, tp, fp, fn, matches, per_cat, duration, cost)
    
    # compute metrics
    results = finalise(aggregates)
    
    # attach dataset summary
    output = {
        'dataset_summary': ds_summary,
        'model_results': results
    }
    
    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2)
    
    # print human‑readable summary
    print("\nDataset summary:")
    print(json.dumps(ds_summary, indent=2))
    print("\nOverall model results:")
    print("Model\tTP\tFP\tFN\tPrec\tRec\tF1\tSpanF1\tIoU\tRuns\tAvgTime(s)\tAvgCost")
    for model_key, res in sorted(results.items()):
        print(f"{model_key}\t{res['TP']}\t{res['FP']}\t{res['FN']}\t"
              f"{res['precision']:.2f}\t{res['recall']:.2f}\t{res['F1']:.2f}\t"
              f"{res['span_F1']:.2f}\t{res['IoU']:.2f}\t{res['runs']}\t"
              f"{res['avg_time_s']:.2f}\t{res['avg_cost']:.4f}")
    
    print(f"\nDetailed results saved to: {output_json}")


if __name__ == '__main__':
    main()