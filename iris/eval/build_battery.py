"""E1 — Golden query battery generator for global search (test-server corpus).

Builds `eval/data/global_search_battery.yaml`: a frozen, labeled, split query
battery for evaluating the global-search rebuild (implementation plan Part 0,
tasks E1.1-E1.4). Deterministic: same inputs + seed => same battery.

TAXONOMY AND QUOTAS (E1.1 — fixed BEFORE any query was written)
    concept-direct        12  "What is X?" over topics present in the corpus
    concept-instance       6  general concept covered only via a specific
                              instance (the PETS shape)
    navigational-title    10  unit/lecture title fragments and prefixes
    factual-entity        10  exam/exercise/channel/faq-shaped questions
    typo                  10  edit-distance perturbations of in-corpus queries
    cross-lingual         10  DE query -> EN content and reverse
    non-latin              4  Arabizi / Arabic script
    acronym                6  RL, DL, NFR, ... (thin-token queries)
    no-content            12  topics provably absent from the corpus (controls
                              for the false-answer gate; absence verified
                              against the extracted inventory)
    multi-course           8  topics present in >1 course (scoping behavior)
    fragment               6  1-2 char / single-word underspecified states
    grounded-negative      4  entity-type questions where the count is zero
    TOTAL                 98

BIAS CONTROLS (E1.2)
  * The inventory (course names, unit names, entity types/titles) is read from
    `eval/data/corpus_inventory.json`, itself regex-extracted from the raw
    investigation log pastes — data, not memory.
  * Generation is template-based with a fixed seed; no query was chosen by
    looking at retrieval output.
  * Every query used during the July 2026 investigation/tuning is listed in
    CONTAMINATED and is barred from the held-out split (they remain useful as
    calibration regression cases).
  * Expected-source labels are only asserted where they follow from the
    inventory itself (title match / unique topic); everything else gets an
    outcome-level label only.

SPLIT (E1.4): seeded 50/50 per class; contaminated queries forced to
calibration. The YAML is the frozen artifact — regenerate only by changing
`VERSION`, never silently.
"""

# Dev tool, not service code: relax cosmetic lint that fights black/f-strings.
# pylint: disable=inconsistent-quotes

from __future__ import annotations

import json
import pprint
import random
import re
from collections import defaultdict
from pathlib import Path

VERSION = 2
SEED = 20260719
INVENTORY = Path(__file__).resolve().parent / "data" / "corpus_inventory.json"
OUT = Path(__file__).resolve().parent / "data" / "global_search_battery.yaml"

# Curated unit-name -> plain-language topic map. Explicit rather than regexed
# so the curation itself is reviewable; units absent from this map are treated
# as junk/untitled (the test corpus is full of 'test'/'fffff'/'Unit 1' decks).
UNIT_TOPICS: dict[str, str] = {
    "02 - Git Basics": "git basics",
    "W02U01_State_pattern": "the state design pattern",
    "W02U02_Template_method_pattern": "the template method pattern",
    "W02U04_Mediator_pattern": "the mediator pattern",
    "W03U01_Factory_method_pattern": "the factory method pattern",
    "W01U02_Patterns_definition": "software patterns",
    "W01U01_Course_organization": "course organization",
    "W02U03 Iteration": "iteration in programming",
    "Abstract classes and interfaces": "abstract classes and interfaces",
    "Inheritance (part 1)": "inheritance in java",
    "Polymorphism": "polymorphism",
    "Designing Scalable and Resilient Microservice Architectures": "microservice architectures",
    "DevOps26 W10 DevOps for AI based Systems": "devops for AI based systems",
    "12 - Error Handling": "error handling",
    "11   SwiftData   Work with Relationships": "swiftdata relationships",
    "20   SwiftUI 13   Complete a game with logic": "building a game with swiftui",
    "04 - SwiftUI 1 - Hello, SwiftUI": "swiftui basics",
    "W01 Introduction": "devops",
    "PETS": "PETS (probabilistic ensembles with trajectory sampling)",
}

# Queries (exact or near-exact) used while investigating/tuning — never held-out.
CONTAMINATED = {
    "what is the builder pattern",
    "what is dynamic programming?",
    "hat is dynamic programming",
    "explain reinforcement learning",
    "what is reinforcmmement leaerning",
    "how do i create a branch in git",
    "how do i create a branch in git?",
    "wie erstelle ich einen branch in git?",
    "introduction ipraktikum",
    "deep learning",
    "ai",
    "rl",
    "hat is rl",
    "dl",
    "design patt",
    "design pattr",
    "design pattrn",
    "deign pattr",
    "reinfor",
    "reinform",
    "reinforce",
    "reinforce le",
    "reinforce lear",
    "stephan",
    "stepha",
    "who is stephan",
    "dev",
    "dev ips",
    "require",
    "requirements",
    "cats",
    "iprak",
    "fr",
    "d",
    "i",
    "explain ai",
    "when is the exam",
    "ipraktikum exercise",
    "ipraktikum exercise?",
    "sorting with the strategy pattern",
    "sorting with the strategy pattern?",
    "programming exercise git",
    "what courses are about machine learning",
    "announcements channel",
    "ba2olak eh hwa ya3ny eh reinforcement learning",
    "ba2olak eh hwa ya3ny eh deep learning",
    "what are communication channels in patterns in software engineering",
    "what are some exercises in the design patterns course",
    "what is the prakitkum?",
}


def parse_inventory() -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Load (course -> units) and (entity type -> titles) from the inventory file."""
    data = json.loads(INVENTORY.read_text(encoding="utf-8"))
    course_units = {c: set(us) for c, us in data["courses"].items()}
    entities = {ty: set(ts) for ty, ts in data["entities"].items()}
    return course_units, entities


def clean_topic(unit_name: str) -> str | None:
    """Map a unit name to its curated topic; None = junk/untitled deck."""
    return UNIT_TOPICS.get(unit_name)


# No-content control topics. Chosen from domains with zero presence in the
# corpus; each is grep-verified against the inventory before being emitted.
ABSENT_TOPICS = [
    ("covalent bonds in chemistry", "en"),
    ("photosynthesis", "en"),
    ("the French revolution", "en"),
    ("human anatomy of the heart", "en"),
    ("contract law in Germany", "de-topic"),
    ("baking sourdough bread", "en"),
    ("IPv6 header format", "en"),
    ("SQL window functions", "en"),
    ("B+ tree index splitting", "en"),
    ("quantum error correction", "en"),
    ("x86 assembly calling conventions", "en"),
    ("Was ist Photosynthese?", "de"),
]

ARABIZI = [
    ("ezay a3mel merge fel git", "picks up Git Basics; answer in Arabic/Arabizi"),
    ("eh hwa el DevOps ya3ny", "DevOps intro units; answer in Arabic/Arabizi"),
    ("ما هو نمط التصميم state", "Arabic script; State pattern slides"),
    ("3ayez afham el sorting algorithms", "sorting content; answer in Arabic/Arabizi"),
]


def q(
    text: str,
    cls: str,
    outcome: str,
    *,
    course: str | None = None,
    unit: str | None = None,
    language: str = "en",
    answer_language: str | None = None,
    notes: str | None = None,
    provenance: str = "generated",
) -> dict:
    return {
        "text": text,
        "class": cls,
        "language": language,
        "provenance": provenance,
        "contaminated": text.lower().strip() in CONTAMINATED,
        "expect": {
            "outcome": outcome,
            **({"course": course} if course else {}),
            **({"unit": unit} if unit else {}),
            "answer_language": answer_language or ("de" if language == "de" else "en"),
            **({"notes": notes} if notes else {}),
        },
    }


def typo(text: str, rng: random.Random) -> str:
    """One deterministic character-level perturbation (drop/swap/duplicate)."""
    letters = [i for i, c in enumerate(text) if c.isalpha()]
    i = rng.choice(letters[2:] or letters)
    op = rng.choice(["drop", "swap", "dup"])
    after = i + 1
    if op == "drop":
        return text[:i] + text[after:]
    if op == "dup":
        return text[:i] + text[i] + text[i:]
    if after < len(text):
        rest = after + 1
        return text[:i] + text[after] + text[i] + text[rest:]
    return text[:-1]


def build() -> dict:
    rng = random.Random(SEED)  # nosec B311 - deterministic sampling, not crypto
    course_units, entities = parse_inventory()

    # topic -> owning courses (for uniqueness / multi-course labels)
    topic_courses: dict[str, set[str]] = defaultdict(set)
    for course, units in course_units.items():
        for u in units:
            t = clean_topic(u)
            if t:
                topic_courses[t].add(course)

    # Verify ABSENT topics truly absent from the inventory text.
    inv_text = " ".join(
        list(topic_courses) + [t for ts in entities.values() for t in ts]
    ).lower()
    for topic, _ in ABSENT_TOPICS:
        key = max(re.findall(r"[a-zA-Zäöüß+]{3,}", topic.lower()), key=len)
        if key in inv_text:
            raise SystemExit(f"absence check failed for control topic: {topic!r}")

    unique = sorted(t for t, cs in topic_courses.items() if len(cs) == 1)
    shared = sorted(t for t, cs in topic_courses.items() if len(cs) > 1)
    rng.shuffle(unique)

    queries: list[dict] = []

    # concept-direct (12): templates over sampled unique topics
    templates = ["What is {t}?", "Explain {t}", "How does {t} work?"]
    for i, t in enumerate(unique[:12]):
        course = next(iter(topic_courses[t]))
        queries.append(
            q(
                templates[i % len(templates)].format(t=t),
                "concept-direct",
                "answered",
                course=course,
            )
        )

    # concept-instance (6): general concept whose only coverage is an instance
    instance_cases = [
        (
            "What is reinforcement learning?",
            "Test Course Nayer Kotry",
            "PETS",
            "only PETS covers it; scoped answer required",
        ),
        (
            "What is model-based machine learning?",
            "Test Course Nayer Kotry",
            "PETS",
            "MBRL instance",
        ),
        (
            "What are behavioral design patterns?",
            "Patterns in Software Engineering (test course)",
            None,
            "covered via State/Template/Command/Mediator instances",
        ),
        (
            "How can animation be made physically realistic?",
            "Test Course Vivien Finley",
            None,
            "spring-damper instance",
        ),
        (
            "What is infrastructure automation?",
            None,
            None,
            "IaC/Docker instances in DevOps + cis units",
        ),
        (
            "How do recommender systems learn preferences?",
            "Test Course Eylül Naz Can",
            "Name Attachment",
            "single-slide instance",
        ),
    ]
    for text, course, unit, notes in instance_cases:
        queries.append(
            q(
                text,
                "concept-instance",
                "answered",
                course=course,
                unit=unit,
                notes=notes,
            )
        )

    # navigational-title (10): titles and prefixes straight from the inventory
    nav_pool = sorted(u for us in course_units.values() for u in us if clean_topic(u))
    rng.shuffle(nav_pool)
    for u in nav_pool[:7]:
        courses = [c for c, us in course_units.items() if u in us]
        queries.append(
            q(u, "navigational-title", "list_relevant", course=courses[0], unit=u)
        )
    for u in nav_pool[7:10]:
        prefix = u[: max(5, len(u) // 2)]
        queries.append(
            q(
                prefix,
                "navigational-title",
                "list_relevant",
                unit=u,
                notes="prefix of a real unit title",
            )
        )

    # factual-entity (10)
    entity_cases = [
        (
            "When does the exam start?",
            "answered",
            "exam entities exist; answer must be per-course scoped or use dates",
        ),
        (
            "Which programming exercises are there?",
            "answered",
            "exercise entities + exercise channels",
        ),
        ("Is there a channel for exam questions?", "answered", "exam channels exist"),
        (
            "Which exercises are about sorting?",
            "answered",
            "Sorting with the Strategy Pattern copies",
        ),
        ("What quiz exercises exist?", "answered", "quiz exam entity exists"),
        (
            "Where do I ask questions about exercises?",
            "answered",
            "exercise-* channels",
        ),
        (
            "Which courses offer a practical course?",
            "answered",
            "Practical Course entities/titles",
        ),
        ("Are there any team exercises?", "answered", "team-exercise entities"),
        ("Show me the announcement channel", "answered", "announcement channels"),
        (
            "What modeling exercises are available?",
            "answered",
            "Modeling Exam Test / modelling channels",
        ),
    ]
    for text, outcome, notes in entity_cases:
        queries.append(q(text, "factual-entity", outcome, notes=notes))

    # typo (10): perturb concept/navigational queries (not the contaminated set)
    typo_bases = [
        x for x in queries if x["class"] in ("concept-direct", "navigational-title")
    ][:10]
    for base in typo_bases:
        queries.append(
            q(
                typo(base["text"], rng),
                "typo",
                base["expect"]["outcome"],
                course=base["expect"].get("course"),
                unit=base["expect"].get("unit"),
                notes=f"typo of: {base['text']}",
            )
        )

    # cross-lingual (10): DE->EN content and EN->DE content
    cross = [
        (
            "Was ist das State Pattern?",
            "de",
            "Patterns in Software Engineering (test course)",
        ),
        ("Wie funktioniert Vererbung in Java?", "de", None),
        ("Erkläre Continuous Integration", "de", None),
        ("Was sind funktionale Anforderungen?", "de", None),
        ("Wie erstelle ich einen Commit?", "de", None),
        (
            "What is discussed in the Mexiko Reise lecture?",
            "en",
            "Test Course Vivien Finley",
        ),
        (
            "What does the German transcription about artificial intelligence say?",
            "en",
            "Test Course Markus Paulsen",
        ),
        ("Summarize the SwiftData relationships unit", "en", "Test Course Senan Aslan"),
        (
            "Was behandelt die Vorlesung über Computergrafik?",
            "de",
            "Test Course Vivien Finley",
        ),
        ("Welche Übungen gibt es zu Sortieralgorithmen?", "de", None),
    ]
    for text, lang, course in cross:
        queries.append(
            q(
                text,
                "cross-lingual",
                "answered",
                course=course,
                language=lang,
                notes="answer must match query language, sources may be other language",
            )
        )

    # non-latin (4)
    for text, notes in ARABIZI:
        lang = "ar" if re.search(r"[؀-ۿ]", text) else "arabizi"
        queries.append(
            q(
                text,
                "non-latin",
                "answered",
                language=lang,
                answer_language="ar",
                notes=notes,
            )
        )

    # acronym (6) — v2: expected course labels added (v1 shipped without any,
    # making the judge unable to match and auto-failing the whole class).
    acronyms = [
        (
            "NFR",
            "list_relevant",
            "Patterns in Software Engineering (test course)",
            "non-functional requirements slides (W01U02 p22/23)",
        ),
        (
            "MBRL",
            "list_relevant",
            "Test Course Nayer Kotry",
            "PETS slides; BM25 cannot tokenize-match",
        ),
        (
            "IaC",
            "list_relevant",
            "Test Course Louis Heinrich",
            "infrastructure as code slides (cis5)",
        ),
        (
            "CI/CD",
            "list_relevant",
            "Practical Course: Interactive Learning SS25",
            "DevOps pipeline content",
        ),
        (
            "OOP",
            "list_relevant",
            "Test Course Patrick Bassner",
            "object orientation lectures",
        ),
        (
            "MPC",
            "list_relevant",
            "Test Course Nayer Kotry",
            "PETS model predictive control (baseline run: PETS #1 at 0.895)",
        ),
    ]
    for text, outcome, course, notes in acronyms:
        queries.append(q(text, "acronym", outcome, course=course, notes=notes))

    # no-content (12): the false-answer controls
    for topic, lang in ABSENT_TOPICS:
        text = topic if topic.endswith("?") or lang == "de" else f"What is {topic}?"
        queries.append(
            q(
                text,
                "no-content",
                "no_sources",
                language="de" if lang == "de" else "en",
                notes="control: absent from corpus, gate must return empty",
            )
        )

    # multi-course (8): topics owned by >1 course
    rng.shuffle(shared)
    for t in shared[:4]:
        queries.append(
            q(
                f"Which courses cover {t}?",
                "multi-course",
                "answered",
                notes=f"topic in courses: {sorted(topic_courses[t])}",
            )
        )
    multi_fixed = [
        "Which courses teach git?",
        "Where is DevOps taught?",
        "Which lectures explain design patterns?",
        "What courses include an introduction to programming?",
        "Which courses cover SwiftUI?",
        "Which lectures talk about exams?",
        "Where can I learn about software engineering?",
    ]
    fixed_needed = 8 - len(shared[:4])
    for text in multi_fixed[:fixed_needed]:
        queries.append(
            q(
                text,
                "multi-course",
                "answered",
                notes="answer must enumerate courses, not pick one",
            )
        )

    # fragment (6): underspecified keystroke states
    for text in ["p", "de", "int", "pat", "exa", "so"]:
        queries.append(
            q(
                text,
                "fragment",
                "list_any",
                notes="no correctness expectation on content; latency + no-crash "
                "+ ideally suppressed by debounce/min-length",
            )
        )

    # grounded-negative (4): counts say zero
    negatives = [
        ("Are there any FAQs in the iPraktikum course?", "ts1 faq count = 0"),
        ("Is there a lecture recording about databases?", "no DB content"),
        (
            "Which exams does the graphics course have?",
            "no exam entity for that course expected",
        ),
        ("Are there FAQ entries about exam registration?", "faq count 0 on ts1"),
    ]
    for text, notes in negatives:
        queries.append(
            q(
                text,
                "grounded-negative",
                "grounded_negative_or_no_sources",
                notes=notes + "; safe only via existence counts",
            )
        )

    # regression (calibration-only by construction): the investigation queries
    # that exposed or verified a specific bug. Their value is exactly that they
    # were tuned on — every one maps to a fixed defect and must stay fixed.
    regression = [
        # (text, class, outcome, course, language, notes) — language explicit,
        # no inference: the battery must never contain detection logic.
        (
            "what is the builder pattern",
            "concept-direct",
            "answered",
            "Patterns in Software Engineering (test course)",
            "the metadata-drop bug query; nulled pre-fix, must answer",
        ),
        (
            "hat is dynamic programming",
            "no-content",
            "no_sources",
            None,
            "the no-content gate verification query (79/79 below threshold)",
        ),
        (
            "what is Reinforcmmement leaerning",
            "typo",
            "answered",
            "Test Course Nayer Kotry",
            "double-typo PETS query; nulled pre-fix",
        ),
        (
            "How do I create a branch in git?",
            "concept-direct",
            "answered",
            "Ipraktikum (test course)",
            "the always-worked regression sentinel",
        ),
        (
            "Wie erstelle ich einen Branch in Git?",
            "cross-lingual",
            "answered",
            "Ipraktikum (test course)",
            "German variant; sources are English",
        ),
        (
            "introduction ipraktikum",
            "navigational-title",
            "list_relevant",
            "Ipraktikum (test course)",
            "the original ranking complaint query",
        ),
        (
            "RL",
            "acronym",
            "list_relevant",
            "Test Course Nayer Kotry",
            "acronym case solved by the reranker (PETS #1)",
        ),
        (
            "ba2olak eh hwa ya3ny eh reinforcement learning",
            "non-latin",
            "answered",
            "Test Course Nayer Kotry",
            "Arabizi; answered in Arabic, PETS-scoped",
        ),
        (
            "who is stephan",
            "factual-entity",
            "no_sources",
            None,
            "junk-context null; LLM null-gate case",
        ),
        (
            "sorting with the strategy pattern",
            "navigational-title",
            "list_relevant",
            "Test Course Senan Aslan",
            "cross-lingual rerank case (German slides, English query)",
        ),
        (
            "when is the exam",
            "factual-entity",
            "answered",
            None,
            "scoping hazard: must be per-course framed, never one course's date",
        ),
        (
            "cats",
            "concept-direct",
            "list_relevant",
            "Test Course Lara Dvorsek",
            "query-conditional junk promotion (transcriptions legitimately #1)",
        ),
    ]
    # Explicit language labels for the fixed regression list — everything is
    # English except these two. Labels are stated, never inferred: the battery
    # must not contain language-detection logic (the product bans it too).
    regression_languages = {
        "Wie erstelle ich einen Branch in Git?": ("de", "de"),
        "ba2olak eh hwa ya3ny eh reinforcement learning": ("arabizi", "ar"),
    }
    for text, cls, outcome, course, notes in regression:
        lang, answer_lang = regression_languages.get(text, ("en", None))
        queries.append(
            q(
                text,
                cls,
                outcome,
                course=course,
                language=lang,
                answer_language=answer_lang,
                notes=notes,
                provenance="investigation",
            )
        )

    # Guard (added after the v1 baseline): a list_relevant query without an
    # expected course/unit label can never be judged a hit — refuse to emit it.
    for item in queries:
        if item["expect"]["outcome"] == "list_relevant" and not (
            item["expect"].get("course") or item["expect"].get("unit")
        ):
            raise SystemExit(f"unlabeled list_relevant query: {item['text']!r}")

    # ---- split (E1.4) ----
    by_class: dict[str, list[dict]] = defaultdict(list)
    for item in queries:
        by_class[item["class"]].append(item)
    for cls, items in by_class.items():
        clean = [x for x in items if not x["contaminated"]]
        rng.shuffle(clean)
        half = len(clean) // 2
        held = set(id(x) for x in clean[:half])
        for x in items:
            x["split"] = "heldout" if id(x) in held else "calibration"

    for i, item in enumerate(queries, 1):
        item_id = f"q{i:03d}"
        item_final = {"id": item_id, **item}
        queries[i - 1] = item_final

    return {
        "meta": {
            "version": VERSION,
            "seed": SEED,
            "frozen_at": "2026-07-19",
            "corpus": "pyris-test.artemis.cit.tum.de (shared test Weaviate)",
            "generator": "eval/build_battery.py",
            "note": "Frozen artifact (E1.4). Do not edit queries in place; "
            "bump VERSION and regenerate. Contaminated queries are "
            "calibration-only by construction.",
            "counts": {
                "total": len(queries),
                "heldout": sum(1 for x in queries if x["split"] == "heldout"),
                "calibration": sum(1 for x in queries if x["split"] == "calibration"),
                "per_class": {
                    cls: len(items) for cls, items in sorted(by_class.items())
                },
            },
        },
        "queries": queries,
    }


def to_yaml(data: dict) -> str:
    """Minimal YAML emitter (no external deps): dicts, lists, scalars."""

    def emit(obj, indent=0):
        pad = "  " * indent
        lines = []
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, (dict, list)) and v:
                    lines.append(f"{pad}{k}:")
                    lines.extend(emit(v, indent + 1))
                else:
                    lines.append(f"{pad}{k}: {scalar(v)}")
        elif isinstance(obj, list):
            for v in obj:
                if isinstance(v, dict):
                    first, *rest = list(v.items())
                    fk, fv = first
                    if isinstance(fv, (dict, list)) and fv:
                        lines.append(f"{pad}- {fk}:")
                        lines.extend(emit(fv, indent + 2))
                    else:
                        lines.append(f"{pad}- {fk}: {scalar(fv)}")
                    for k, val in rest:
                        if isinstance(val, (dict, list)) and val:
                            lines.append(f"{pad}  {k}:")
                            lines.extend(emit(val, indent + 2))
                        else:
                            lines.append(f"{pad}  {k}: {scalar(val)}")
                else:
                    lines.append(f"{pad}- {scalar(v)}")
        return lines

    def scalar(v):
        if isinstance(v, bool):
            return "true" if v else "false"
        if v is None:
            return "null"
        if isinstance(v, (int, float)):
            return str(v)
        s = str(v)
        if re.search(r"[:#\[\]{}'\"|>&*!%@`]", s) or s != s.strip():
            return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
        return s

    return "\n".join(emit(data)) + "\n"


def emit_python_module(data: dict) -> Path:
    """Emit the battery as a shipped module so the SERVER-SIDE runner
    (src/iris/global_search_battery.py) can execute it without filesystem or
    token access — the test-branch deployment path is: code -> image -> logs.
    """
    target = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "iris"
        / "global_search_battery_data.py"
    )
    queries_repr = pprint.pformat(data["queries"], width=76, sort_dicts=False)
    body = (
        '"""GENERATED by eval/build_battery.py — do not edit by hand.\n\n'
        "Frozen golden query battery (E1) embedded for the in-process runner.\n"
        'Regenerate: python eval/build_battery.py\n"""\n\n'
        f"VERSION = {data['meta']['version']}\n\n"
        f"QUERIES = {queries_repr}\n"
    )
    target.write_text(body, encoding="utf-8")
    return target


def main() -> None:
    data = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(to_yaml(data), encoding="utf-8")
    module = emit_python_module(data)
    print(f"embedded module -> {module}")
    meta = data["meta"]["counts"]
    print(f"battery v{VERSION} -> {OUT}")
    print(
        f"total={meta['total']} heldout={meta['heldout']} "
        f"calibration={meta['calibration']}"
    )
    for cls, n in meta["per_class"].items():
        held = sum(
            1 for x in data["queries"] if x["class"] == cls and x["split"] == "heldout"
        )
        contaminated = sum(
            1 for x in data["queries"] if x["class"] == cls and x["contaminated"]
        )
        print(f"  {cls:20s} {n:3d}  heldout={held:2d}  contaminated={contaminated}")


if __name__ == "__main__":
    main()
