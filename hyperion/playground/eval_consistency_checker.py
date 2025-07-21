#!/usr/bin/env python
"""
Simple evaluation script for the consistency checker.
Stores model output to JSON.

Usage:
    cd hyperion
    poetry run python playground/eval_consistency_checker.py --exercise "ISE22/H01E02-Object_Oriented_Programming"
    poetry run python playground/eval_consistency_checker.py --exercise "ISE22/H01E02-Object_Oriented_Programming" \
        --model-name "openai:gpt-4o" --output "custom_output.json"
"""

import sys
import json
import argparse
from pathlib import Path
from typing import Dict, Any

# Add the project root to the path so we can import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.creation_steps.models import RepositoryFile, Repository
from app.creation_steps.step8_review_and_refine.consistency_check.models import (
    ConsistencyCheckRequest,
)
from app.creation_steps.step8_review_and_refine.consistency_check.handler import (
    ConsistencyCheck,
)


def load_repository_files(repo_path: Path) -> list:
    """Load files from a repository directory."""
    files = []
    if repo_path.exists():
        for file_path in repo_path.rglob("*"):
            if file_path.is_file() and not file_path.name.startswith("."):
                relative_path = file_path.relative_to(repo_path)
                try:
                    content = file_path.read_text(encoding="utf-8")
                    files.append(
                        RepositoryFile(path=str(relative_path), content=content)
                    )
                except UnicodeDecodeError:
                    # Skip binary files
                    continue
    return files


def load_exercise_from_dataset(exercise_path: str) -> Dict[str, Any]:
    """Load an exercise from the dataset."""
    base_path = Path(__file__).parent.parent / "data" / exercise_path

    if not base_path.exists():
        raise FileNotFoundError(f"Exercise not found: {exercise_path}")

    # Load problem statement
    problem_statement_path = base_path / "problem-statement.md"
    if not problem_statement_path.exists():
        raise FileNotFoundError(
            f"Problem statement not found: {problem_statement_path}"
        )

    problem_statement = problem_statement_path.read_text(encoding="utf-8")

    # Load repositories
    template_files = load_repository_files(base_path / "template")
    solution_files = load_repository_files(base_path / "solution")
    test_files = load_repository_files(base_path / "tests")

    return {
        "problem_statement": problem_statement,
        "template_files": template_files,
        "solution_files": solution_files,
        "test_files": test_files,
    }


def evaluate_exercise(exercise_path: str, model_name: str) -> Dict[str, Any]:
    """Evaluate consistency for a single exercise."""
    print(f"Evaluating: {exercise_path}")

    # Load exercise data
    exercise_data = load_exercise_from_dataset(exercise_path)

    # Create repositories
    template_repo = Repository(files=exercise_data["template_files"])
    solution_repo = Repository(files=exercise_data["solution_files"])
    test_repo = Repository(files=exercise_data["test_files"])

    # Create request
    request = ConsistencyCheckRequest(
        problem_statement=exercise_data["problem_statement"],
        template_repository=template_repo,
        solution_repository=solution_repo,
        test_repository=test_repo,
    )

    # Initialize consistency checker
    consistency_checker = ConsistencyCheck(model_name=model_name)

    # Run consistency check
    response = consistency_checker.check(request)

    # Return the response directly - Pydantic models are JSON serializable
    return {
        "exercise_path": exercise_path,
        "response": response.model_dump(),  # Convert Pydantic model to dict
    }


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Evaluate consistency checker")
    parser.add_argument("--exercise", "-e", required=True, help="Exercise to evaluate")
    parser.add_argument(
        "--output", "-o", default="consistency_output.json", help="Output file name"
    )
    parser.add_argument(
        "--model-name",
        "-m",
        default="openai:o3-mini",
        help="Model name to use for consistency checking",
    )

    args = parser.parse_args()

    try:
        result = evaluate_exercise(
            args.exercise,
            model_name=args.model_name,
        )

        # Save result
        output_dir = Path(__file__).parent / "consistency_results"
        output_dir.mkdir(exist_ok=True)
        output_file = output_dir / args.output

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        print(f"Found {len(result['response']['issues'])} issues")
        print(f"Result saved to: {output_file}")

    except Exception as e:
        print(f"Error: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
