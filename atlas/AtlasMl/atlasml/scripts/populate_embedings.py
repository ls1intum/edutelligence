"""
populate_weaviate.py
--------------------

Usage:
    python populate_weaviate.py \
        --exercises ./samples/exercises.csv \
        --competencies ./samples/competencies.csv \
        --relations ./samples/relations.csv
"""

from __future__ import annotations
import argparse
import pandas as pd
from dataclasses import dataclass, field
from collections import defaultdict
from pathlib import Path

from atlasml.ml.MLPipelines.PipelineWorkflows import PipelineWorkflows


@dataclass
class Competency:
    id: str
    title: str
    description: str = ""

@dataclass
class ExerciseWithCompetencies:
    id: str
    title: str
    description: str
    competencies: list[Competency] = field(default_factory=list)


def load_competencies(path: Path) -> dict[str, Competency]:
    df = pd.read_csv(path, dtype={'id': str})
    return {
        row.id: Competency(
            id=str(row.id),
            title=row.title,
            description=row.description if "description" in row else "",
        )
        for _, row in df.iterrows()
    }


def load_exercises(path: Path) -> dict[str, ExerciseWithCompetencies]:
    df = pd.read_csv(path)
    return {
        row.exercise_id: ExerciseWithCompetencies(
            id=str(row.exercise_id),
            title=row.exercise_title,
            description=row.exercise_problem_statement,
        )
        for _, row in df.iterrows()
    }

def attach_relations(
    relations_path: Path,
    exercises: dict[str, ExerciseWithCompetencies],
    competencies: dict[str, Competency],
) -> None:
    """
    Fills each ExerciseWithCompetencies.competencies list in-place according to the relations CSV (competency_id,exercise_id).
    """
    rel_df = pd.read_csv(relations_path)

    mapping: dict[str, list[str]] = defaultdict(list)
    for _, row in rel_df.iterrows():
        mapping[row.exercise_id].append(row.competency_id)

    for ex_id, comp_ids in mapping.items():
        if ex_id not in exercises:
            print(f"⚠️  exercise_id {ex_id} in relations but missing in exercises.csv")
            continue
        exercises[ex_id].competencies = [
            competencies[cid]
            for cid in comp_ids
            if cid in competencies
        ]


def main() -> None:
    base = Path(__file__).parent / "samples"
    competencies = load_competencies(base / "competencies.csv")
    exercises = load_exercises(base / "exercises.csv")

    pipeline = PipelineWorkflows() 

    print("➡️  Uploading competencies …")
    pipeline.initial_competencies(list(competencies.values()))

    print("➡️  Uploading exercises …")  
    pipeline.initial_exercises(list(exercises.values()))

    print("➡️  Computing per‑competency cluste  r centroids …")
    pipeline.initial_cluster_pipeline()

    print("✅ Done. "
          f"Upserted {len(competencies)} competencies and {len(exercises)} exercises.")


if __name__ == "__main__":
    main()
