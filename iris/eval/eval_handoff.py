"""
Exhaustive rule-coverage table for GlobalSearchPipeline._determine_handoff.

The function is pure, so every branch is enumerated with constructed source sets.
Output: pass/fail table for the thesis (results chapter, handoff section).

Usage: .venv/bin/python eval/eval_handoff.py
"""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("APPLICATION_YML_PATH", str(REPO_ROOT / "application.local.yml"))
os.environ.setdefault("LLM_CONFIG_PATH", str(REPO_ROOT / "llm_config.local.yml"))
sys.path.insert(0, str(REPO_ROOT / "src"))

from iris.config import settings  # noqa: E402

settings.set_env_vars()

from iris.domain.search.lecture_search_dto import (  # noqa: E402
    CourseInfo,
    GlobalSearchSourceDTO,
    HandoffType,
    LectureInfo,
)
from iris.pipeline.global_search_pipeline import GlobalSearchPipeline  # noqa: E402


def src(
    source_type: str, course_id: int, entity_id: int = 1, lecture_id: int | None = None
) -> GlobalSearchSourceDTO:
    return GlobalSearchSourceDTO(
        sourceType=source_type,
        entityId=entity_id,
        course=CourseInfo(id=course_id, name=f"Course {course_id}"),
        title=f"{source_type}-{entity_id}",
        lecture=(
            LectureInfo(id=lecture_id, name=f"Lecture {lecture_id}")
            if lecture_id is not None
            else None
        ),
    )


CASES = [
    # (description, sources, expected handoff type, expected ids)
    ("empty source list", [], None, {}),
    (
        "single exercise, nothing else",
        [src("exercise", 7, entity_id=42)],
        HandoffType.EXERCISE,
        {"courseId": 7, "exerciseId": 42},
    ),
    (
        "two exercises, same course",
        [src("exercise", 7, 42), src("exercise", 7, 43)],
        HandoffType.COURSE,
        {"courseId": 7},
    ),
    (
        "all sources from one lecture",
        [
            src("lecture_unit_slide", 7, 1, lecture_id=5),
            src("lecture_unit_slide", 7, 2, lecture_id=5),
        ],
        HandoffType.LECTURE,
        {"courseId": 7, "lectureId": 5},
    ),
    (
        "two different lectures, same course",
        [
            src("lecture_unit_slide", 7, 1, lecture_id=5),
            src("lecture_unit_slide", 7, 2, lecture_id=6),
        ],
        HandoffType.COURSE,
        {"courseId": 7},
    ),
    (
        "lecture + exercise, same course",
        [src("lecture_unit_slide", 7, 1, lecture_id=5), src("exercise", 7, 42)],
        HandoffType.COURSE,
        {"courseId": 7},
    ),
    (
        "exercise + channel, same course",
        [src("exercise", 7, 42), src("channel", 7, 9)],
        HandoffType.COURSE,
        {"courseId": 7},
    ),
    (
        "channel only, one course",
        [src("channel", 7, 9)],
        HandoffType.COURSE,
        {"courseId": 7},
    ),
    ("faq only, one course", [src("faq", 7, 3)], HandoffType.COURSE, {"courseId": 7}),
    (
        "sources across two courses -> top-ranked course",
        [src("lecture_unit_slide", 7, 1, lecture_id=5), src("exercise", 9, 42)],
        HandoffType.LECTURE,
        {"courseId": 7, "lectureId": 5},
    ),
    (
        "two lectures across two courses -> top course's lecture",
        [
            src("lecture_unit_slide", 7, 1, lecture_id=5),
            src("lecture_unit_slide", 9, 2, lecture_id=8),
        ],
        HandoffType.LECTURE,
        {"courseId": 7, "lectureId": 5},
    ),
    (
        "exercise top-ranked, other course filtered out",
        [src("exercise", 7, 42), src("channel", 9, 9)],
        HandoffType.EXERCISE,
        {"courseId": 7, "exerciseId": 42},
    ),
]


def main() -> None:
    fn = GlobalSearchPipeline._determine_handoff
    print(f"{'case':<48} {'expected':<10} {'got':<10} result")
    print("-" * 84)
    failures = 0
    for desc, sources, expected_type, expected_ids in CASES:
        h = fn(sources)
        got_type = h.type if h else None
        ok = got_type == expected_type
        if ok and h is not None:
            for key, val in expected_ids.items():
                attr = {
                    "courseId": "course_id",
                    "exerciseId": "exercise_id",
                    "lectureId": "lecture_id",
                }[key]
                if getattr(h, attr, None) != val:
                    ok = False
        failures += not ok
        print(
            f"{desc:<48} {str(expected_type and expected_type.value):<10} "
            f"{str(got_type and got_type.value):<10} {'PASS' if ok else 'FAIL'}"
        )
    print("-" * 84)
    print(f"{len(CASES) - failures}/{len(CASES)} passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
