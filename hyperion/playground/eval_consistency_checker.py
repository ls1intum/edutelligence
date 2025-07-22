#!/usr/bin/env python
"""
Simple evaluation script for the consistency checker.
Stores model output to JSON.

Usage:
    cd hyperion
    poetry run python playground/eval_consistency_checker.py --exercise "ISE22/H01E02-Object_Oriented_Programming"
    poetry run python playground/eval_consistency_checker.py --exercise "ISE22/H01E02-Object_Oriented_Programming" \
        --model-name "openai:o4-mini" --output "custom_output.json"
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
    ProgrammingLanguage,
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


def detect_programming_language(template_files: list) -> ProgrammingLanguage:
    """Detect programming language based on file extensions in template repository."""
    file_extensions = set()
    
    for file in template_files:
        file_path = file.path
        if "." in file_path:
            ext = "." + file_path.split(".")[-1]
            file_extensions.add(ext)
    
    # Check for Java files
    if ".java" in file_extensions:
        return ProgrammingLanguage.JAVA
    
    # Check for Python files
    if ".py" in file_extensions:
        return ProgrammingLanguage.PYTHON
    
    # Default to Java if we can't determine
    print(f"Warning: Could not detect programming language from extensions: {file_extensions}")
    print("Defaulting to Java")
    return ProgrammingLanguage.JAVA


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


def evaluate_exercise(exercise_path: str, model_name: str, programming_language: ProgrammingLanguage = None) -> Dict[str, Any]:
    """Evaluate consistency for a single exercise."""
    print(f"Evaluating: {exercise_path}")

    # Load exercise data
    exercise_data = load_exercise_from_dataset(exercise_path)

    # Create repositories
    template_repo = Repository(files=exercise_data["template_files"])
    solution_repo = Repository(files=exercise_data["solution_files"])
    test_repo = Repository(files=exercise_data["test_files"])

    # Use provided language or detect from template files
    if programming_language is None:
        programming_language = detect_programming_language(exercise_data["template_files"])
        print(f"Detected programming language: {programming_language}")
    else:
        print(f"Using specified programming language: {programming_language}")

    # Create request
    request = ConsistencyCheckRequest(
        problem_statement=exercise_data["problem_statement"],
        template_repository=template_repo,
        programming_language=programming_language,
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
        "programming_language": programming_language,
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
        default="openai:o4-mini",
        help="Model name to use for consistency checking",
    )
    parser.add_argument(
        "--language",
        "-l",
        choices=["java", "python"],
        help="Programming language (auto-detected if not specified)",
    )

    args = parser.parse_args()

    # Convert language string to enum if provided
    programming_language = None
    if args.language:
        programming_language = ProgrammingLanguage(args.language)

    try:
        result = evaluate_exercise(
            args.exercise,
            model_name=args.model_name,
            programming_language=programming_language,
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
