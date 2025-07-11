#!/usr/bin/env python
"""
Simple evaluation script for the consistency checker.
Stores model output to JSON.

Usage:
    cd hyperion
    poetry run python playground/eval_consistency_checker.py --exercise "ISE22/H01E02-Object_Oriented_Programming"
"""

import sys
import json
import argparse
from pathlib import Path
from typing import Dict, Any

# Add the project root to the path so we can import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.grpc import hyperion_pb2
from app.creation_steps.step8_review_and_refine.consistency_check import ConsistencyCheck


def load_repository_files(repo_path: Path) -> list:
    """Load files from a repository directory."""
    files = []
    if repo_path.exists():
        for file_path in repo_path.rglob("*"):
            if file_path.is_file() and not file_path.name.startswith('.'):
                relative_path = file_path.relative_to(repo_path)
                try:
                    content = file_path.read_text(encoding='utf-8')
                    files.append(hyperion_pb2.RepositoryFile(
                        path=str(relative_path),
                        content=content
                    ))
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
        raise FileNotFoundError(f"Problem statement not found: {problem_statement_path}")
    
    problem_statement = problem_statement_path.read_text(encoding='utf-8')
    
    # Load repositories
    template_files = load_repository_files(base_path / "template")
    solution_files = load_repository_files(base_path / "solution")
    test_files = load_repository_files(base_path / "tests")
    
    return {
        "problem_statement": problem_statement,
        "template_files": template_files,
        "solution_files": solution_files,
        "test_files": test_files
    }


def convert_issue_to_json(issue) -> Dict[str, Any]:
    """Convert a ConsistencyIssue protobuf to JSON-serializable dict."""
    return {
        "description": issue.description,
        "severity": hyperion_pb2.ConsistencyIssueSeverity.Name(issue.severity),
        "type": hyperion_pb2.ConsistencyIssueType.Name(issue.type),
        "category": hyperion_pb2.ConsistencyIssueCategory.Name(issue.category),
        "primary_location": {
            "type": hyperion_pb2.ArtifactType.Name(issue.primary_location.type),
            "file_path": issue.primary_location.file_path,
            "start_line": issue.primary_location.start_line,
            "end_line": issue.primary_location.end_line
        },
        "related_locations": [
            {
                "type": hyperion_pb2.ArtifactType.Name(loc.type),
                "file_path": loc.file_path,
                "start_line": loc.start_line,
                "end_line": loc.end_line
            }
            for loc in issue.related_locations
        ],
        "suggested_fix": issue.suggested_fix
    }


def evaluate_exercise(exercise_path: str, model_name: str, model_provider: str) -> Dict[str, Any]:
    """Evaluate consistency for a single exercise."""
    print(f"Evaluating: {exercise_path}")
    
    # Load exercise data
    exercise_data = load_exercise_from_dataset(exercise_path)
    
    # Create repositories
    template_repo = hyperion_pb2.Repository(files=exercise_data["template_files"])
    solution_repo = hyperion_pb2.Repository(files=exercise_data["solution_files"])
    test_repo = hyperion_pb2.Repository(files=exercise_data["test_files"])
    
    # Create request
    request = hyperion_pb2.ConsistencyCheckRequest(
        problem_statement=exercise_data["problem_statement"],
        template_repository=template_repo,
        solution_repository=solution_repo,
        test_repository=test_repo
    )
    
    # Initialize consistency checker
    consistency_checker = ConsistencyCheck(model_name=model_name, model_provider=model_provider)

    # Run consistency check
    response = consistency_checker.check_consistency(request)
    
    # Convert issues to JSON format
    issues_json = [convert_issue_to_json(issue) for issue in response.issues]
    trace_id = response.metadata.traceId
    
    return {
        "exercise_path": exercise_path,
        "issues": issues_json,
        "trace_id": trace_id,
    }


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Evaluate consistency checker")
    parser.add_argument("--exercise", "-e", required=True, help="Exercise to evaluate")
    parser.add_argument("--output", "-o", default="consistency_output.json", help="Output file name")
    parser.add_argument("--model-name", "-m", default="o3-mini", help="Model name to use for consistency checking")
    parser.add_argument("--model-provider", "-p", default="openai", help="Model provider to use for consistency checking")
    
    args = parser.parse_args()
    
    try:
        result = evaluate_exercise(args.exercise, model_name=args.model_name, model_provider=args.model_provider)
        
        # Save result
        output_dir = Path(__file__).parent / "consistency_results"
        output_dir.mkdir(exist_ok=True)
        output_file = output_dir / args.output
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        
        print(f"Found {len(result['issues'])} issues")
        print(f"Result saved to: {output_file}")
        
    except Exception as e:
        print(f"Error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
