"""Edge-case probe of the deployed intent classifier.

Families:
  A punctuation pairs   B form variants      C length-padding pairs
  D incomplete (behav)  E far-domain trigger F far-domain skip
  G garbage (behav)     H mixed signals (behav)
  J multi-sentence      K keyboard artifacts
Gold None => behavioral family (distribution reported, not scored).
Screening: cosine vs 2,859 training rows with the BASE paraphrase model
(>0.90 dropped; families E/F additionally require max cosine < 0.70).
"""
import csv, re, sys, json
from pathlib import Path
from collections import Counter, defaultdict
import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from iris.pipeline.shared.global_search_intent_classifier import _get_classifier  # noqa: E402

T, S = "trigger_ai", "skip_ai"

def P(qid, fam, q, gold, lang="en", pair=None, tag=""):
    return dict(id=qid, family=fam, query=q, gold=gold, lang=lang, pair=pair, tag=tag)

probes = []
# A ── punctuation pairs
A_know = ["how does garbage collection decide what to free",
          "why does my regression overfit with more features",
          "what is the intuition behind eigenvalues",
          "when should I use a linked list instead of an array",
          "how do routers pick the shortest path",
          "what does statistical significance actually mean"]
A_nav = ["where is the sample solution for sheet 3",
         "which room is the retake exam in",
         "when is the submission deadline for project 2",
         "where can I find last semester's slides",
         "which channel is for organizational questions",
         "where do I register for the tutorial group"]
i = 0
for base, gold in [(q, T) for q in A_know] + [(q, S) for q in A_nav]:
    i += 1
    probes.append(P(f"A{i}b", "A_punct", base, gold, pair=f"A{i}", tag="bare"))
    probes.append(P(f"A{i}q", "A_punct", base + "?", gold, pair=f"A{i}", tag="qmark"))
for tag, suf in [("period", "."), ("bang", "!"), ("ellipsis", "...")]:
    probes.append(P(f"A1{tag}", "A_punct", A_know[0] + suf, T, pair="A1", tag=tag))
    probes.append(P(f"A7{tag}", "A_punct", A_nav[0] + suf, S, pair="A7", tag=tag))

# B ── form variants
Bs = [("I keep confusing precision and recall", T, "en"),
      ("I still do not understand pointers", T, "en"),
      ("the difference between TCP and UDP confuses me", T, "en"),
      ("ich verstehe den Unterschied zwischen Stack und Heap nicht", T, "de"),
      ("explain memoization step by step", T, "en"),
      ("erkläre mir Vererbung", T, "de"),
      ("could you please explain what a monad is", T, "en"),
      ("könntest du mir bitte erklären was ein Deadlock ist", T, "de"),
      ("why does gradient clipping not fix exploding activations", T, "en"),
      ("can you show me where the week 2 recording is?", S, "en"),
      ("could you tell me when the exam registration closes?", S, "en"),
      ("kannst du mir zeigen wo die Folien von letzter Woche sind?", S, "de"),
      ("I am looking for the grading breakdown", S, "en"),
      ("ich suche das Skript zum Kurs", S, "de")]
for n, (q, g, l) in enumerate(Bs, 1):
    probes.append(P(f"B{n}", "B_form", q, g, lang=l))

# C ── length-padding pairs
FILL_EN = " - I already looked through the course page twice and could not find anything about this anywhere"
FILL_DE = " - ich habe schon überall im Kurs gesucht und leider nichts dazu gefunden"
Cs = [("what is dynamic programming", T, "en", FILL_EN),
      ("how does https encryption work", T, "en", FILL_EN),
      ("was ist Rekursion", T, "de", FILL_DE),
      ("why use version control", T, "en", FILL_EN),
      ("office hours for the databases course", S, "en", FILL_EN),
      ("slides from the first week", S, "en", FILL_EN),
      ("Übungsblatt für nächste Woche", S, "de", FILL_DE),
      ("past exam papers", S, "en", FILL_EN)]
for n, (q, g, l, f) in enumerate(Cs, 1):
    probes.append(P(f"C{n}s", "C_length", q, g, lang=l, pair=f"C{n}", tag="short"))
    probes.append(P(f"C{n}l", "C_length", q + f, g, lang=l, pair=f"C{n}", tag="padded"))

# D ── incomplete (behavioral)
Ds = ["what is the difference between", "how do I", "explain the", "why does the",
      "what happens when", "wie funktioniert", "was ist der Unterschied zwischen",
      "can you explain", "I have a question about", "how to", "definition of", "erkläre"]
for n, q in enumerate(Ds, 1):
    probes.append(P(f"D{n}", "D_incomplete", q, None, lang="de" if re.search(r"wie|was|erkläre", q) else "en"))

# E ── far-domain knowledge (gold trigger, structure test)
Es = [("why does yeast make bread rise", "en"), ("how does a clutch in a manual car work", "en"),
      ("what makes a contract legally binding", "en"), ("why do antibiotics not work against viruses", "en"),
      ("how does the offside rule work in football", "en"), ("why does metal feel colder than wood", "en"),
      ("how do noise cancelling headphones work", "en"), ("why is the sky red at sunset", "en"),
      ("how does compound interest work", "en"), ("warum wird Teig mit Hefe luftig", "de"),
      ("wie funktioniert eine Wärmepumpe", "de"), ("why do cats purr", "en"),
      ("how does a lock pick work", "en"), ("what causes inflation in an economy", "en")]
for n, (q, l) in enumerate(Es, 1):
    probes.append(P(f"E{n}", "E_fardomain_know", q, T, lang=l))

# F ── far-domain navigational analogues (gold skip)
Fs = ["season 3 episode 7", "gate B37", "invoice 2024-113", "platform 9 departure",
      "table for two at 7pm", "room 4021", "flight LH1810 status", "track 5 on the album",
      "aisle 12", "ticket #48213"]
for n, q in enumerate(Fs, 1):
    probes.append(P(f"F{n}", "F_fardomain_nav", q, S))

# G ── garbage / noise (behavioral)
Gs = ["asdkfjhalsdkjfh", "🤔🤔🤔", "??", "!!!", "42",
      "https://example.com/watch?v=abc123", "int main(void) { return 0; }",
      "....", "ok", "test test test"]
for n, q in enumerate(Gs, 1):
    probes.append(P(f"G{n}", "G_garbage", q, None))

# H ── mixed signals (behavioral)
Hs = ["sheet 5 question about dijkstra complexity",
      "Übungsblatt 3 warum konvergiert gradient descent",
      "exam 2023 what topics on hashing",
      "lecture 4 slide 12 what does the diagram mean",
      "homework help binary trees",
      "quiz 2 explanation for question 5",
      "Folien Kapitel 3 Zusammenfassung bitte",
      "project 1 how to parse json in java"]
for n, q in enumerate(Hs, 1):
    probes.append(P(f"H{n}", "H_mixed", q, None, lang="de" if re.search(r"Übung|Folien", q) else "en"))

# J ── multi-sentence
Js = [("I watched the lecture twice. I still do not get how attention works. Can someone explain it differently", T, "en"),
      ("Hi! I missed the first week. Where do I find the recordings", S, "en"),
      ("Quick question. What exactly is tail recursion", T, "en"),
      ("Hallo zusammen. Ich schreibe nächste Woche die Klausur. Warum ist Mergesort stabil", T, "de"),
      ("Guten Tag. Ich finde die Anmeldung nicht. Wo melde ich mich für die Übung an", S, "de"),
      ("The tutorial mentioned invariants. What is a loop invariant", T, "en"),
      ("I am new here. Which channel should I use for admin questions", S, "en"),
      ("Sorry if this was asked before. How does paging differ from segmentation", T, "en")]
for n, (q, g, l) in enumerate(Js, 1):
    probes.append(P(f"J{n}", "J_multisentence", q, g, lang=l))

# K ── keyboard artifacts
Ks = [("erklaere mir Baeume in Java", T, "de"), ("uebung 7 loesung", S, "de"),
      ("WIE FUNKTIONIERT DNS", T, "de"), ("WO IST DER HOERSAAL", S, "de"),
      ("wat is a semaphore", T, "en"), ("hwo does caching work", T, "en"),
      ("pls explain b-trees", T, "en"), ("wo find ich die folien vong letzter woche", S, "de")]
for n, (q, g, l) in enumerate(Ks, 1):
    probes.append(P(f"K{n}", "K_keyboard", q, g, lang=l))

print(f"probe count before screening: {len(probes)}")

# ── training data + label stats ────────────────────────────────────────────────
with open(REPO / "models/global_search_intent/training_data.csv", encoding="utf-8") as f:
    training = [(r["Query"], r["Intent"]) for r in csv.DictReader(f)]
tl = Counter(l for _, l in training)
long_rows = [(q, l) for q, l in training if len(q.split()) >= 12]
short_rows = [(q, l) for q, l in training if len(q.split()) <= 2]
stats_lines = [
    f"- training label balance: {dict(tl)}",
    f"- rows with >=12 words: {len(long_rows)}, of which trigger: {sum(1 for _, l in long_rows if l == T)}",
    f"- rows with <=2 words: {len(short_rows)}, of which trigger: {sum(1 for _, l in short_rows if l == T)}",
    f"- rows ending with '?': {sum(1 for q, _ in training if q.strip().endswith('?'))}",
]
print("\n".join(stats_lines))

# ── screening with base encoder ───────────────────────────────────────────────
from sentence_transformers import SentenceTransformer
base = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
def norm(q): return re.sub(r"\s+", " ", q.strip().lower())
train_norm = {norm(q) for q, _ in training}
train_emb = base.encode([q for q, _ in training], normalize_embeddings=True, batch_size=128, show_progress_bar=False)
probe_emb = base.encode([p["query"] for p in probes], normalize_embeddings=True, batch_size=128, show_progress_bar=False)
sims = probe_emb @ train_emb.T
maxsim = sims.max(axis=1)
kept, dropped = [], []
for p, ms in zip(probes, maxsim):
    p["max_train_cos"] = float(ms)
    limit = 0.70 if p["family"].startswith(("E_", "F_")) else 0.90
    if norm(p["query"]) in train_norm or ms >= limit:
        dropped.append(p)
    else:
        kept.append(p)
print(f"screened out: {len(dropped)}, kept: {len(kept)}")

# ── run deployed classifier ───────────────────────────────────────────────────
clf = _get_classifier()
assert clf is not None
for p in kept:
    enc = clf._tokenizer([p["query"]], return_tensors="np", padding=True, truncation=True, max_length=128)
    ort_inputs = {k: v for k, v in enc.items() if k in clf._input_names}
    tok = clf._session.run(clf._output_names, ort_inputs)[0]
    mask = enc["attention_mask"][:, :, np.newaxis].astype(np.float32)
    emb = (tok * mask).sum(axis=1) / mask.sum(axis=1).clip(min=1e-9)
    proba = clf._head.predict_proba(emb)[0]
    cls = int(np.argmax(proba))
    p["pred"] = T if cls == 1 else S
    p["conf"] = float(proba[cls])

# ── reporting ─────────────────────────────────────────────────────────────────
out = Path(__file__).parent / "results"
out.mkdir(exist_ok=True)
md = ["# Intent classifier edge-case probe", ""]
md += ["## Training-set composition", *stats_lines, ""]
md.append(f"## Probes: {len(kept)} kept ({len(dropped)} screened out)\n")

for fam in sorted({p['family'] for p in kept}):
    rows = [p for p in kept if p["family"] == fam]
    scored = [p for p in rows if p["gold"]]
    md.append(f"### {fam} (n={len(rows)})")
    if scored:
        acc = sum(p["pred"] == p["gold"] for p in scored)
        md.append(f"- accuracy: {acc}/{len(scored)}")
        for p in scored:
            if p["pred"] != p["gold"]:
                md.append(f"  - MISS [{p['id']}] {p['query']!r} gold={p['gold']} pred={p['pred']} conf={p['conf']:.3f}")
    else:
        dist = Counter(p["pred"] for p in rows)
        md.append(f"- behavioral distribution: {dict(dist)}")
        for p in rows:
            md.append(f"  - [{p['id']}] {p['query']!r} -> {p['pred']} ({p['conf']:.3f})")
    md.append("")

# paired flip analysis (A and C)
for fam, key in [("A_punct", "punctuation"), ("C_length", "length padding")]:
    pairs = defaultdict(dict)
    for p in kept:
        if p["family"] == fam and p["pair"]:
            pairs[p["pair"]][p["tag"]] = p
    flips = []
    for pid, variants in pairs.items():
        base_p = variants.get("bare") or variants.get("short")
        if not base_p:
            continue
        for tag, v in variants.items():
            if v is base_p:
                continue
            if v["pred"] != base_p["pred"]:
                flips.append((pid, tag, base_p["query"], base_p["pred"], v["pred"]))
    md.append(f"### Paired {key} flips: {len(flips)}")
    for f_ in flips:
        md.append(f"  - {f_[0]} [{f_[1]}] {f_[2]!r}: {f_[3]} -> {f_[4]}")
    md.append("")

report = "\n".join(md)
(out / "intent_probe.md").write_text(report)
with open(out / "intent_probe.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["id", "family", "query", "gold", "pred", "conf", "lang", "pair", "tag", "max_train_cos"])
    w.writeheader()
    for p in kept:
        w.writerow({k: p.get(k) for k in w.fieldnames})
print(report)
