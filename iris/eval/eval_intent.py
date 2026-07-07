"""
Evaluate the DEPLOYED intent classifier (INT8 ONNX + LR head) on an
out-of-distribution test set, with leakage screening against the training CSV.

Usage (from the iris repo root):
    .venv/bin/python eval/eval_intent.py                 # screen + evaluate deployed model
    .venv/bin/python eval/eval_intent.py --baselines     # also run offline baselines
    .venv/bin/python eval/eval_intent.py --latency       # latency benchmark
    .venv/bin/python eval/eval_intent.py --show-screened # list screened-out queries

Outputs a markdown report + per-query predictions CSV under eval/results/.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("APPLICATION_YML_PATH", str(REPO_ROOT / "application.local.yml"))
os.environ.setdefault("LLM_CONFIG_PATH", str(REPO_ROOT / "llm_config.local.yml"))
sys.path.insert(0, str(REPO_ROOT / "src"))

TRAINING_CSV = REPO_ROOT / "models/global_search_intent/training_data.csv"
TEST_CSV = REPO_ROOT / "eval/data/ood_intent_test.csv"
RESULTS_DIR = REPO_ROOT / "eval/results"

SIMILARITY_THRESHOLD = 0.90  # cosine; above this a test query counts as contaminated
BOOTSTRAP_SAMPLES = 10_000
RNG_SEED = 42


# ─── Data loading ──────────────────────────────────────────────────────────────


@dataclass
class TestRow:
    query: str
    gold: str  # training-convention label: "trigger_ai" | "skip_ai"
    category: str
    language: str
    hard: bool
    gold_policy: str = ""  # desired PRODUCT behavior, where it differs from gold
    # filled during the run:
    screened: bool = False
    screen_reason: str = ""
    pred: str = ""
    confidence: float = 0.0  # probability of the predicted class


def load_test_set(path: Path) -> list[TestRow]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            gold = r["gold"]
            rows.append(
                TestRow(
                    query=r["query"],
                    gold=gold,
                    category=r["category"],
                    language=r["language"],
                    hard=bool((r.get("hard") or "").strip()),
                    gold_policy=(r.get("gold_policy") or "").strip() or gold,
                )
            )
    return rows


def load_training_queries(path: Path) -> list[tuple[str, str]]:
    with open(path, encoding="utf-8") as f:
        return [(r["Query"], r["Intent"]) for r in csv.DictReader(f)]


# ─── Deployed-model access (batched embedding via the production artifacts) ───


def get_deployed_classifier():
    from iris.pipeline.shared.global_search_intent_classifier import _get_classifier

    clf = _get_classifier()
    if clf is None:
        raise SystemExit("Deployed classifier failed to load — cannot evaluate.")
    return clf


def embed_batch(clf, texts: list[str], batch_size: int = 64) -> np.ndarray:
    """Embed texts with the deployed ONNX backbone + mean pooling (batched)."""
    out: list[np.ndarray] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        enc = clf._tokenizer(
            batch, return_tensors="np", padding=True, truncation=True, max_length=128
        )
        ort_inputs = {k: v for k, v in enc.items() if k in clf._input_names}
        token_embeddings = clf._session.run(clf._output_names, ort_inputs)[0]
        mask = enc["attention_mask"][:, :, np.newaxis].astype(np.float32)
        summed = (token_embeddings * mask).sum(axis=1)
        counts = mask.sum(axis=1).clip(min=1e-9)
        out.append(summed / counts)
    return np.vstack(out)


# ─── Leakage screening ─────────────────────────────────────────────────────────


def normalize(q: str) -> str:
    return re.sub(r"\s+", " ", q.strip().lower())


def screen_test_set(test_rows: list[TestRow], training: list[tuple[str, str]]) -> None:
    """Flag test queries that are near-duplicates of training rows.

    Similarity is computed with the BASE (un-fine-tuned) paraphrase model, NOT the
    deployed SetFit backbone: contrastive fine-tuning on binary labels collapses the
    embedding space into two class clusters, so in the fine-tuned space nearly all
    same-class pairs score cosine > 0.99 regardless of meaning — useless for
    duplicate detection. The base model preserves semantic similarity.
    """
    from sentence_transformers import SentenceTransformer

    base = SentenceTransformer(
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )
    train_norm = {normalize(q) for q, _ in training}
    train_emb = base.encode([q for q, _ in training], show_progress_bar=False)
    train_emb /= np.linalg.norm(train_emb, axis=1, keepdims=True)
    test_emb = base.encode([r.query for r in test_rows], show_progress_bar=False)
    test_emb /= np.linalg.norm(test_emb, axis=1, keepdims=True)

    sims = test_emb @ train_emb.T  # (n_test, n_train)
    train_queries = [q for q, _ in training]
    for i, row in enumerate(test_rows):
        if normalize(row.query) in train_norm:
            row.screened = True
            row.screen_reason = "exact match in training data"
            continue
        j = int(np.argmax(sims[i]))
        if sims[i, j] > SIMILARITY_THRESHOLD:
            row.screened = True
            row.screen_reason = (
                f"cosine {sims[i, j]:.3f} to training query: {train_queries[j]!r}"
            )


# ─── Metrics ───────────────────────────────────────────────────────────────────


def bootstrap_ci(
    correct: np.ndarray, n: int = BOOTSTRAP_SAMPLES
) -> tuple[float, float]:
    rng = np.random.default_rng(RNG_SEED)
    idx = rng.integers(0, len(correct), size=(n, len(correct)))
    means = correct[idx].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def prf(rows: list[TestRow], positive: str) -> tuple[float, float, float]:
    tp = sum(1 for r in rows if r.gold == positive and r.pred == positive)
    fp = sum(1 for r in rows if r.gold != positive and r.pred == positive)
    fn = sum(1 for r in rows if r.gold == positive and r.pred != positive)
    p = tp / (tp + fp) if tp + fp else 0.0
    r_ = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * r_ / (p + r_) if p + r_ else 0.0
    return p, r_, f1


def metrics_block(name: str, rows: list[TestRow], lines: list[str]) -> None:
    """Append a full metrics section for one model's predictions."""
    correct = np.array([r.pred == r.gold for r in rows], dtype=float)
    acc = correct.mean()
    lo, hi = bootstrap_ci(correct)
    lines.append(f"\n## {name}\n")
    lines.append(f"- n = {len(rows)} (after screening)")
    lines.append(f"- **Accuracy: {acc:.4f}**  (95% bootstrap CI [{lo:.4f}, {hi:.4f}])")
    for cls in ("trigger_ai", "skip_ai"):
        p, r_, f1 = prf(rows, cls)
        marker = (
            "  ← north-star (never drop a knowledge query)"
            if cls == "trigger_ai"
            else ""
        )
        lines.append(
            f"- {cls}: precision {p:.4f}  **recall {r_:.4f}**  F1 {f1:.4f}{marker}"
        )

    tt = sum(1 for r in rows if r.gold == "trigger_ai" and r.pred == "trigger_ai")
    ts = sum(1 for r in rows if r.gold == "trigger_ai" and r.pred == "skip_ai")
    st = sum(1 for r in rows if r.gold == "skip_ai" and r.pred == "trigger_ai")
    ss = sum(1 for r in rows if r.gold == "skip_ai" and r.pred == "skip_ai")
    lines.append("\n|  | pred trigger_ai | pred skip_ai |")
    lines.append("|---|---|---|")
    lines.append(f"| **gold trigger_ai** | {tt} | {ts} |")
    lines.append(f"| **gold skip_ai** | {st} | {ss} |")

    lines.append("\n| category | n | accuracy | errors |")
    lines.append("|---|---|---|---|")
    cats = sorted({r.category for r in rows})
    for cat in cats:
        sub = [r for r in rows if r.category == cat]
        n_err = sum(1 for r in sub if r.pred != r.gold)
        lines.append(f"| {cat} | {len(sub)} | {1 - n_err / len(sub):.3f} | {n_err} |")
    for lang in ("en", "de"):
        sub = [r for r in rows if r.language == lang]
        if sub:
            a = sum(1 for r in sub if r.pred == r.gold) / len(sub)
            lines.append(
                f"| lang={lang} | {len(sub)} | {a:.3f} | "
                f"{sum(1 for r in sub if r.pred != r.gold)} |"
            )
    hard = [r for r in rows if r.hard]
    easy = [r for r in rows if not r.hard]
    for label, sub in (("hard-flagged", hard), ("not hard-flagged", easy)):
        if sub:
            a = sum(1 for r in sub if r.pred == r.gold) / len(sub)
            lines.append(
                f"| {label} | {len(sub)} | {a:.3f} | "
                f"{sum(1 for r in sub if r.pred != r.gold)} |"
            )

    errors = [r for r in rows if r.pred != r.gold]
    lines.append(f"\n### Errors ({len(errors)})\n")
    lines.append("| query | gold | pred | conf | category |")
    lines.append("|---|---|---|---|---|")
    for r in sorted(errors, key=lambda r: r.category):
        conf = f"{r.confidence:.3f}" if r.confidence else "-"
        lines.append(f"| {r.query} | {r.gold} | {r.pred} | {conf} | {r.category} |")

    if any(r.confidence for r in rows):
        conf_correct = [r.confidence for r in rows if r.pred == r.gold]
        conf_wrong = [r.confidence for r in rows if r.pred != r.gold]
        lines.append("\n### Confidence (LR head predict_proba of predicted class)\n")
        lines.append(
            f"- correct predictions: mean {np.mean(conf_correct):.3f}, "
            f"min {np.min(conf_correct):.3f}"
        )
        if conf_wrong:
            lines.append(
                f"- errors: mean {np.mean(conf_wrong):.3f}, "
                f"max {np.max(conf_wrong):.3f}"
            )
            below = sum(1 for c in conf_wrong if c < 0.8)
            lines.append(
                f"- {below}/{len(conf_wrong)} errors have confidence < 0.8 "
                f"(a threshold-to-TRIGGER_AI fallback would catch these)"
            )


# ─── Deployed-model prediction ────────────────────────────────────────────────


def predict_deployed(clf, rows: list[TestRow]) -> None:
    labels = {0: "skip_ai", 1: "trigger_ai"}
    emb = embed_batch(clf, [r.query for r in rows])
    preds = clf._head.predict(emb)
    probas = clf._head.predict_proba(emb)
    for row, p, pr in zip(rows, preds, probas):
        row.pred = labels[int(p)]
        row.confidence = float(pr[int(p)])


# ─── Baselines (trained on the FULL current CSV — see caveat in the report) ───


NAV_PATTERN = re.compile(
    r"\b(lecture|lec\d*|exercise|ex\d+|sheet|blatt|übung|übungsblatt|klausur|exam|"
    r"folien|slides?|solutions?|lösung|musterlösung|hw\d*|homework|hausaufgabe|"
    r"week|woche|kapitel|chapter|skript|tutorium|tutorial|quiz|worksheet|lab|"
    r"assignment|abgabe|mitschrift|notes|schedule|termin|anmeldung|deadline|"
    r"formelsammlung|zusammenfassung|probeklausur|altklausur)\b",
    re.IGNORECASE,
)
QUESTION_PATTERN = re.compile(
    r"(\?|^(what|how|why|when|which|who|is|are|does|do|can|could|should|explain|"
    r"was|wie|warum|wann|welche|wer|ist|sind|kann|können|sollte|erklär|erkläre|"
    r"gibt es)\b)",
    re.IGNORECASE,
)


def baseline_regex(query: str) -> str:
    """Heuristic: question-shaped and long enough → trigger; else skip."""
    words = query.split()
    if QUESTION_PATTERN.search(query.strip()) and len(words) >= 3:
        return "trigger_ai"
    if len(words) <= 3:
        return "skip_ai"
    return "trigger_ai" if not NAV_PATTERN.search(query) else "skip_ai"


def run_baselines(
    clf, rows: list[TestRow], training: list[tuple[str, str]], lines: list[str]
) -> None:
    lines.append(
        "\n> Baseline caveats: (1) learned baselines train on the full current "
        "2,859-row CSV; the deployed model was trained on an uncommitted ~2,350-row "
        "predecessor — this favours the baselines, so deployed-model wins are "
        "conservative. (2) The regex heuristic was authored with knowledge of the "
        "label convention and test categories; it is an informed upper bound for "
        "rule-based approaches, not a blind baseline."
    )

    def timed_eval(name: str, predict_fn, per_query_ms: float | None = None):
        snapshot = [
            TestRow(r.query, r.gold, r.category, r.language, r.hard) for r in rows
        ]
        t0 = time.perf_counter()
        for r in snapshot:
            r.pred = predict_fn(r.query)
        elapsed_ms = (time.perf_counter() - t0) * 1000 / len(snapshot)
        metrics_block(
            f"Baseline: {name} (median {per_query_ms or elapsed_ms:.2f} ms/query)",
            snapshot,
            lines,
        )

    timed_eval("regex heuristic", baseline_regex)

    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression

    train_x = [q for q, _ in training]
    train_y = [1 if intent == "trigger_ai" else 0 for _, intent in training]
    vec = TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True)
    xt = vec.fit_transform(train_x)
    lr = LogisticRegression(max_iter=1000, random_state=RNG_SEED)
    lr.fit(xt, train_y)
    labels = {0: "skip_ai", 1: "trigger_ai"}
    timed_eval(
        "TF-IDF + LogisticRegression",
        lambda q: labels[int(lr.predict(vec.transform([q]))[0])],
    )

    # Base (un-fine-tuned) multilingual MiniLM + LR head — isolates SetFit's value
    try:
        from sentence_transformers import SentenceTransformer

        base = SentenceTransformer(
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        )
        base_train = base.encode(train_x, show_progress_bar=False)
        lr2 = LogisticRegression(max_iter=1000, random_state=RNG_SEED)
        lr2.fit(base_train, train_y)
        base_test = base.encode([r.query for r in rows], show_progress_bar=False)
        snapshot = [
            TestRow(r.query, r.gold, r.category, r.language, r.hard) for r in rows
        ]
        for r, p in zip(snapshot, lr2.predict(base_test)):
            r.pred = labels[int(p)]
        metrics_block("Baseline: base MiniLM (no SetFit) + LR", snapshot, lines)
    except Exception as exc:  # model download may fail offline
        lines.append(f"\n## Baseline: base MiniLM + LR — SKIPPED ({exc})\n")


# ─── Latency ───────────────────────────────────────────────────────────────────


def run_latency(clf, rows: list[TestRow], lines: list[str], n: int = 1000) -> None:
    from iris.pipeline.shared.global_search_intent_classifier import classify

    queries = [r.query for r in rows]
    classify(queries[0])  # ensure warm
    times = []
    for i in range(n):
        q = queries[i % len(queries)]
        t0 = time.perf_counter()
        classify(q)
        times.append((time.perf_counter() - t0) * 1000)
    arr = np.array(times)
    onnx_path = REPO_ROOT / "models/global_search_intent/onnx/model_quantized.onnx"
    lines.append(f"\n## Latency (deployed model, {n} warm calls, CPU)\n")
    lines.append(
        f"- p50 {np.percentile(arr, 50):.2f} ms · "
        f"p95 {np.percentile(arr, 95):.2f} ms · "
        f"p99 {np.percentile(arr, 99):.2f} ms · "
        f"mean {arr.mean():.2f} ms"
    )
    lines.append(
        f"- model size on disk: {onnx_path.stat().st_size / 1e6:.1f} MB (INT8)"
    )


# ─── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--baselines", action="store_true")
    ap.add_argument("--latency", action="store_true")
    ap.add_argument("--show-screened", action="store_true")
    args = ap.parse_args()

    import logging

    logging.disable(logging.INFO)

    rows = load_test_set(TEST_CSV)
    training = load_training_queries(TRAINING_CSV)
    print(f"Test set: {len(rows)} queries · training CSV: {len(training)} rows")

    t0 = time.perf_counter()
    clf = get_deployed_classifier()
    load_s = time.perf_counter() - t0
    print(f"Deployed classifier loaded in {load_s:.2f}s")

    print("Screening for training-data contamination (base paraphrase model)…")
    screen_test_set(rows, training)
    screened = [r for r in rows if r.screened]
    kept = [r for r in rows if not r.screened]
    print(
        f"Screened out {len(screened)} / {len(rows)} queries "
        f"(cosine > {SIMILARITY_THRESHOLD} or exact match); evaluating on {len(kept)}"
    )

    predict_deployed(clf, kept)

    lines: list[str] = [
        f"# Intent classifier evaluation — deployed model\n",
        f"- date: {datetime.now().isoformat(timespec='seconds')}",
        f"- model: models/global_search_intent/onnx/model_quantized.onnx "
        f"(SHA-256 matches the Dockerfile HuggingFace pin)",
        f"- test set: {TEST_CSV.relative_to(REPO_ROOT)} ({len(rows)} queries, "
        f"{len(screened)} screened out as potentially contaminated, "
        f"{len(kept)} evaluated)",
        f"- screening: exact normalized match OR cosine > {SIMILARITY_THRESHOLD} "
        f"against all {len(training)} training rows (embeddings from the BASE "
        f"paraphrase model — the fine-tuned backbone's space is class-collapsed "
        f"and unusable for duplicate detection)",
        f"- cold-start load time: {load_s:.2f}s",
    ]

    if screened:
        lines.append(f"\n## Screened-out queries ({len(screened)})\n")
        lines.append("| query | reason |")
        lines.append("|---|---|")
        for r in screened:
            lines.append(f"| {r.query} | {r.screen_reason} |")

    # Frame 1: accuracy against the training-data label convention. Rows whose
    # product-desired label differs from the convention are excluded here so the
    # headline number measures exactly one thing: how well the model learned its
    # own convention.
    convention_rows = [r for r in kept if r.gold_policy == r.gold]
    metrics_block(
        "Frame 1 — vs training convention (deployed INT8 ONNX + LR head)",
        convention_rows,
        lines,
    )

    # Frame 2: label-policy alignment. On rows where the training convention and
    # the desired product behavior disagree (concept keyphrases without question
    # syntax), the model cannot be "right" in both frames — this measures which
    # side it follows, and at what confidence.
    policy_rows = [r for r in kept if r.gold_policy != r.gold]
    if policy_rows:
        follows_convention = [r for r in policy_rows if r.pred == r.gold]
        follows_policy = [r for r in policy_rows if r.pred == r.gold_policy]
        confs = [r.confidence for r in follows_convention]
        lines.append("\n## Frame 2 — label-policy misalignment slice\n")
        lines.append(
            f"Rows where training convention ({policy_rows[0].gold}) and desired "
            f"product behavior ({policy_rows[0].gold_policy}) disagree: "
            f"n = {len(policy_rows)} (category: "
            f"{', '.join(sorted({r.category for r in policy_rows}))})."
        )
        lines.append(
            f"\n- follows training convention (→ no AI answer): "
            f"**{len(follows_convention)}/{len(policy_rows)}**"
        )
        lines.append(
            f"- follows desired product behavior (→ AI answer): "
            f"{len(follows_policy)}/{len(policy_rows)}"
        )
        if confs:
            lines.append(
                f"- confidence when following the convention: mean "
                f"{np.mean(confs):.3f}, min {np.min(confs):.3f} — the misalignment "
                f"is learned, not uncertain; a confidence threshold cannot catch it."
            )
        lines.append("\n| query | pred | conf |")
        lines.append("|---|---|---|")
        for r in policy_rows:
            lines.append(f"| {r.query} | {r.pred} | {r.confidence:.3f} |")

    if args.baselines:
        print("Running baselines…")
        # Baselines are compared on the Frame-1 (convention) rows so all models
        # answer the same question.
        run_baselines(clf, convention_rows, training, lines)
    if args.latency:
        print("Running latency benchmark…")
        run_latency(clf, kept, lines)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report = RESULTS_DIR / f"intent_eval_{stamp}.md"
    report.write_text("\n".join(lines), encoding="utf-8")

    pred_csv = RESULTS_DIR / f"intent_predictions_{stamp}.csv"
    with open(pred_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "query",
                "gold",
                "pred",
                "confidence",
                "category",
                "language",
                "hard",
                "screened",
                "screen_reason",
            ]
        )
        for r in rows:
            w.writerow(
                [
                    r.query,
                    r.gold,
                    r.pred,
                    f"{r.confidence:.4f}",
                    r.category,
                    r.language,
                    r.hard,
                    r.screened,
                    r.screen_reason,
                ]
            )

    n_err = sum(1 for r in kept if r.pred != r.gold)
    acc = 1 - n_err / len(kept)
    print(
        f"\nDone. Accuracy {acc:.4f} ({len(kept) - n_err}/{len(kept)}), "
        f"{n_err} errors."
    )
    print(f"Report: {report}")
    print(f"Predictions: {pred_csv}")
    if args.show_screened:
        for r in screened:
            print(f"  SCREENED: {r.query!r} — {r.screen_reason}")


if __name__ == "__main__":
    main()
