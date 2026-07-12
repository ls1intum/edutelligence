"""Follow-up probe: keyphrase +/- '?', naturally long navigational, caps matrix."""
import csv, re, sys
from pathlib import Path
from collections import Counter, defaultdict
import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from iris.pipeline.shared.global_search_intent_classifier import _get_classifier  # noqa: E402

T, S = "trigger_ai", "skip_ai"
probes = []
def P(qid, fam, q, gold, lang="en", pair=None, tag=""):
    probes.append(dict(id=qid, family=fam, query=q, gold=gold, lang=lang, pair=pair, tag=tag))

# 1 ── keyphrase +/- '?' pairs (Frame-2 style concept keyphrases)
KP = [("spectral clustering assumptions", "en"), ("b-tree insertion complexity", "en"),
      ("tcp congestion window growth", "en"), ("cache coherence protocols overview", "en"),
      ("bias variance decomposition proof", "en"), ("hauptsatz der thermodynamik herleitung", "de"),
      ("normalformen relationale datenbanken", "de"), ("dijkstra korrektheit beweis", "de"),
      ("virtual memory page replacement policies", "en"), ("type inference hindley milner", "en"),
      ("markov chain stationary distribution conditions", "en"), ("red black tree rotation cases", "en"),
      ("kondensator lade kurve erklaerung", "de"), ("fourier transform time shift property", "en"),
      ("mutex vs spinlock tradeoffs", "en")]
for n, (q, l) in enumerate(KP, 1):
    P(f"Q{n}b", "Q_keyphrase", q, None, lang=l, pair=f"Q{n}", tag="bare")
    P(f"Q{n}q", "Q_keyphrase", q + "?", None, lang=l, pair=f"Q{n}", tag="qmark")

# 2 ── naturally long navigational (no synthetic suffix)
LN = [("could someone tell me where I can download the annotated slides from week three, I could not find them in the lectures section", "en"),
      ("does anyone know in which room the exercise session takes place on thursday afternoons this semester", "en"),
      ("I wanted to ask when exactly the registration for the final exam opens and where I need to sign up for it", "en"),
      ("weiß jemand wo ich die Musterlösung für das fünfte Übungsblatt finde, im Kursbereich sehe ich sie nicht", "de"),
      ("kann mir jemand sagen in welchem Kanal die organisatorischen Ankündigungen für dieses Semester gepostet werden", "de")]
for n, (q, l) in enumerate(LN, 1):
    P(f"L{n}", "L_longnav", q, S, lang=l)

# 3 ── caps matrix
CM = [("WIE FUNKTIONIERT EIN BETRIEBSSYSTEM", T, "de", "caps_de_know"),
      ("WARUM IST QUICKSORT SCHNELLER ALS BUBBLESORT", T, "de", "caps_de_know"),
      ("WAS MACHT EIN COMPILER", T, "de", "caps_de_know"),
      ("HOW DOES A FIREWALL WORK", T, "en", "caps_en_know"),
      ("WHY DO WE NEED NORMALIZATION", T, "en", "caps_en_know"),
      ("WHAT IS A DEADLOCK", T, "en", "caps_en_know"),
      ("WO IST DER SEMINARRAUM", S, "de", "caps_de_nav"),
      ("WANN IST DIE KLAUSUR", S, "de", "caps_de_nav"),
      ("wie funktioniert ein betriebssystem", T, "de", "lower_de_know"),
      ("warum ist quicksort schneller als bubblesort", T, "de", "lower_de_know"),
      ("was macht ein compiler", T, "de", "lower_de_know"),
      ("Wie funktioniert ein Betriebssystem", T, "de", "mixed_de_know")]
for n, (q, g, l, tag) in enumerate(CM, 1):
    P(f"M{n}", "M_caps", q, g, lang=l, tag=tag)

# screening
with open(REPO / "models/global_search_intent/training_data.csv", encoding="utf-8") as f:
    training = [(r["Query"], r["Intent"]) for r in csv.DictReader(f)]
from sentence_transformers import SentenceTransformer
base = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
def norm(q): return re.sub(r"\s+", " ", q.strip().lower())
train_norm = {norm(q) for q, _ in training}
temb = base.encode([q for q, _ in training], normalize_embeddings=True, batch_size=128)
pemb = base.encode([p["query"] for p in probes], normalize_embeddings=True, batch_size=128)
maxsim = (pemb @ temb.T).max(axis=1)
kept = []
for p, ms in zip(probes, maxsim):
    p["max_train_cos"] = float(ms)
    if norm(p["query"]) in train_norm or ms >= 0.90:
        continue
    kept.append(p)
print(f"kept {len(kept)}/{len(probes)}")

clf = _get_classifier(); assert clf
for p in kept:
    enc = clf._tokenizer([p["query"]], return_tensors="np", padding=True, truncation=True, max_length=128)
    tok = clf._session.run(clf._output_names, {k: v for k, v in enc.items() if k in clf._input_names})[0]
    mask = enc["attention_mask"][:, :, np.newaxis].astype(np.float32)
    emb = (tok * mask).sum(axis=1) / mask.sum(axis=1).clip(min=1e-9)
    proba = clf._head.predict_proba(emb)[0]
    p["pred"] = T if int(np.argmax(proba)) == 1 else S
    p["conf"] = float(proba.max())

md = ["# Follow-up probe", ""]
# keyphrase pairs: flip analysis
pairs = defaultdict(dict)
for p in kept:
    if p["family"] == "Q_keyphrase":
        pairs[p["pair"]][p["tag"]] = p
flips, stay = [], Counter()
for pid, v in sorted(pairs.items()):
    if "bare" in v and "qmark" in v:
        b, q = v["bare"], v["qmark"]
        stay[(b["pred"], q["pred"])] += 1
        if b["pred"] != q["pred"]:
            flips.append(f"  - {pid}: {b['query']!r} {b['pred']}({b['conf']:.2f}) -> +? {q['pred']}({q['conf']:.2f})")
md.append(f"## Keyphrase +/- '?' ({len(pairs)} pairs)")
md.append(f"- (bare_pred, qmark_pred) counts: { {f'{a}->{b2}': c for (a,b2),c in stay.items()} }")
md += (["- flips:"] + flips) if flips else ["- flips: NONE"]
md.append("")
md.append("## Naturally long navigational (gold skip)")
for p in kept:
    if p["family"] == "L_longnav":
        mark = "OK " if p["pred"] == p["gold"] else "MISS"
        md.append(f"  - {mark} [{p['lang']}] {p['query'][:70]!r} -> {p['pred']} ({p['conf']:.3f})")
md.append("")
md.append("## Caps matrix")
for p in kept:
    if p["family"] == "M_caps":
        mark = "OK " if p["pred"] == p["gold"] else "MISS"
        md.append(f"  - {mark} [{p['tag']}] {p['query'][:55]!r} -> {p['pred']} ({p['conf']:.3f})")
report = "\n".join(md)
(Path(__file__).parent / "results" / "intent_probe2.md").write_text(report)
print(report)
