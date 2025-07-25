#!/usr/bin/env python
"""
Enhanced evaluation script for the consistency checker with trace export support.
Stores model output to JSON and exports LLM traces.

Usage:
    cd hyperion
    # Evaluate base exercise
    poetry run python playground/eval_consistency_checker.py --exercise "ITP2425/H01E01-Lectures"

    # Evaluate specific variant
    poetry run python playground/eval_consistency_checker.py --exercise "ITP2425/H01E01-Lectures" --variant "001"

    # Evaluate all variants of an exercise
    poetry run python playground/eval_consistency_checker.py --exercise "ITP2425/H01E01-Lectures" --all-variants

    # Custom model and output settings
    poetry run python playground/eval_consistency_checker.py --exercise "ITP2425/H01E01-Lectures" \
        --model-name "openai:o4-mini" --variant "001"
"""

import sys
import json
import argparse
import os
import uuid
import traceback
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

# Add the project root to the path so we can import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import LangSmith client for trace export
try:
    from langsmith import Client as LangSmithClient

    LANGSMITH_AVAILABLE = True
except ImportError:
    LANGSMITH_AVAILABLE = False
    print("Warning: LangSmith not available. Trace export will be disabled.")

# Import these at module level since they don't affect tracing
from app.creation_steps.models import RepositoryFile, Repository


def get_git_commit_id() -> Optional[str]:
    """
    Get the current git commit ID (SHA).

    Returns:
        The current git commit ID as a string, or None if not available
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=Path(__file__).parent.parent,  # Run from hyperion root directory
        )
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            print(f"Warning: Could not get git commit ID: {result.stderr.strip()}")
            return None
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        FileNotFoundError,
    ) as e:
        print(f"Warning: Could not get git commit ID: {e}")
        return None


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


def detect_programming_language(template_files: list):
    """Detect programming language based on file extensions in template repository."""
    # Import here to avoid issues with tracing setup
    from app.creation_steps.step8_review_and_refine.consistency_check.models import (
        ProgrammingLanguage,
    )

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
    print(
        f"Warning: Could not detect programming language from extensions: {file_extensions}"
    )
    print("Defaulting to Java")
    return ProgrammingLanguage.JAVA


def export_langsmith_traces(
    trace_id: str, project_name: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Export LangSmith traces for the given trace ID.

    Args:
        trace_id: The LangSmith trace ID to export
        project_name: Optional project name (defaults to environment or "hyperion-consistency-check")

    Returns:
        List of serialized trace run dictionaries
    """
    if not LANGSMITH_AVAILABLE:
        print("LangSmith not available - skipping trace export")
        return []

    if not trace_id:
        print("No trace ID provided - skipping trace export")
        return []

    try:
        client = LangSmithClient()

        # Use project name from environment or default
        if project_name is None:
            project_name = os.environ.get(
                "LANGCHAIN_PROJECT", "hyperion-consistency-check"
            )

        print(f"Exporting traces from project: {project_name}")
        print(f"Looking for trace ID: {trace_id}")

        # Query runs from LangSmith using the specific trace ID
        runs = list(
            client.list_runs(
                project_name=project_name,
                trace_id=trace_id,
                limit=100,  # Should be enough for one trace
            )
        )

        print(f"Found {len(runs)} LangSmith runs for trace {trace_id}")

        # Convert runs to serializable format
        traces = []
        for run in runs:
            try:
                # Convert run to dict and handle serialization
                run_dict = {
                    "id": str(run.id),
                    "name": run.name,
                    "run_type": run.run_type,
                    "start_time": (
                        run.start_time.isoformat() if run.start_time else None
                    ),
                    "end_time": run.end_time.isoformat() if run.end_time else None,
                    "status": run.status,
                    "inputs": run.inputs,
                    "outputs": run.outputs,
                    "tags": run.tags,
                    "parent_run_id": (
                        str(run.parent_run_id) if run.parent_run_id else None
                    ),
                    "trace_id": str(run.trace_id) if run.trace_id else None,
                    "dotted_order": run.dotted_order,
                    "session_id": str(run.session_id) if run.session_id else None,
                }

                # Include extra data if available
                for attr in ["extra", "error", "events"]:
                    if hasattr(run, attr) and getattr(run, attr):
                        run_dict[attr] = getattr(run, attr)

                traces.append(run_dict)
            except Exception as e:
                print(f"Warning: Could not serialize run {run.id}: {e}")
                # Add minimal info for failed runs
                traces.append(
                    {
                        "id": str(run.id),
                        "name": getattr(run, "name", "Unknown"),
                        "error": f"Serialization failed: {str(e)}",
                    }
                )

        print(f"Successfully exported {len(traces)} traces")

        # Print debug info about what we found
        if traces:
            print("Trace runs found:")
            for trace in traces:
                print(
                    f"  - {trace.get('name', 'No name')} ({trace.get('run_type', 'unknown')})"
                )

        return traces

    except Exception as e:
        print(f"Error exporting LangSmith traces: {e}")
        if os.environ.get("DEBUG"):
            traceback.print_exc()
        return []


def create_output_files(
    result: Dict[str, Any], traces: List[Dict[str, Any]], output_dir: Path, run_id: str
) -> tuple[Path, Path]:
    """Create timestamped output files for results and traces."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Create result file
    result_file = output_dir / f"{timestamp}_{run_id}_result.json"
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    # Create trace file
    trace_data = {
        "run_id": run_id,
        "timestamp": timestamp,
        "commit_id": result.get("commit_id"),  # Include commit ID in trace metadata
        "trace_count": len(traces),
        "traces": traces,
    }
    trace_file = output_dir / f"{timestamp}_{run_id}_trace.json"
    with open(trace_file, "w", encoding="utf-8") as f:
        json.dump(trace_data, f, indent=2, ensure_ascii=False)

    return result_file, trace_file


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


def evaluate_exercise(
    exercise_path: str,
    model_name: str,
    programming_language=None,
    export_traces: bool = True,
) -> tuple[Dict[str, Any], List[Dict[str, Any]], str]:
    """
    Evaluate consistency for a single exercise.

    Args:
        exercise_path: Path to the exercise to evaluate
        model_name: Name of the model to use for consistency checking
        programming_language: Programming language (auto-detected if None)
        export_traces: Whether to export LangSmith traces

    Returns:
        tuple of (result_dict, traces_list, run_id)
    """
    print(f"Evaluating: {exercise_path}")

    # Generate unique run ID
    run_id = str(uuid.uuid4())[:8]
    start_time = datetime.now()

    # Set up LangChain tracing environment
    os.environ["LANGCHAIN_RUN_ID"] = run_id
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    if "LANGCHAIN_PROJECT" not in os.environ:
        os.environ["LANGCHAIN_PROJECT"] = "hyperion-consistency-check"

    print(
        f"Tracing setup - Run ID: {run_id}, Project: {os.environ.get('LANGCHAIN_PROJECT')}"
    )

    # Import consistency check classes after setting up tracing
    from app.creation_steps.step8_review_and_refine.consistency_check.models import (
        ConsistencyCheckRequest,
    )
    from app.creation_steps.step8_review_and_refine.consistency_check.handler import (
        ConsistencyCheck,
    )

    # Load exercise data
    exercise_data = load_exercise_from_dataset(exercise_path)

    # Create repositories
    template_repo = Repository(files=exercise_data["template_files"])
    solution_repo = Repository(files=exercise_data["solution_files"])
    test_repo = Repository(files=exercise_data["test_files"])

    # Use provided language or detect from template files
    if programming_language is None:
        programming_language = detect_programming_language(
            exercise_data["template_files"]
        )
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

    # Extract trace ID from response metadata
    langsmith_trace_id = response.metadata.trace_id
    print(f"Consistency check completed with trace ID: {langsmith_trace_id}")

    # Get git commit ID
    commit_id = get_git_commit_id()
    if commit_id:
        print(f"Git commit ID: {commit_id}")

    # Prepare result
    result = {
        "exercise_path": exercise_path,
        "programming_language": str(programming_language),  # Ensure serializable
        "run_id": run_id,
        "timestamp": start_time.isoformat(),
        "model_name": model_name,
        "langsmith_trace_id": langsmith_trace_id,
        "commit_id": commit_id,  # Include git commit ID
        "response": response.model_dump(),
    }

    # Export traces if requested
    traces = []
    if export_traces:
        print("Exporting LangSmith traces...")
        traces = export_langsmith_traces(langsmith_trace_id)

    return result, traces, run_id


def get_all_variants(exercise_path: str) -> List[str]:
    """Get all variant IDs for an exercise."""
    base_path = Path(__file__).parent.parent / "data" / exercise_path
    variants_dir = base_path / "variants"

    if not variants_dir.exists():
        return []

    variants = []
    for variant_dir in variants_dir.iterdir():
        if variant_dir.is_dir() and variant_dir.name.isdigit():
            variants.append(variant_dir.name)

    return sorted(variants)


def evaluate_variant(
    exercise_path: str,
    variant_id: str,
    model_name: str,
    programming_language=None,
) -> tuple[Path, Path]:
    """
    Evaluate a specific variant and save outputs to timestamped files.

    Args:
        exercise_path: Base exercise path (e.g., "ITP2425/H01E01-Lectures")
        variant_id: Variant identifier (e.g., "001")
        model_name: Model name to use for consistency checking
        programming_language: Programming language (auto-detected if None)

    Returns:
        tuple of (result_file_path, trace_file_path)
    """
    variant_exercise_path = f"{exercise_path}/variants/{variant_id}"

    # Run evaluation
    result, traces, run_id = evaluate_exercise(
        variant_exercise_path, model_name, programming_language
    )

    # Create output directory for variant
    base_path = Path(__file__).parent.parent / "data" / exercise_path
    output_dir = base_path / "variants" / variant_id / "outputs"

    # Save files
    result_file, trace_file = create_output_files(result, traces, output_dir, run_id)

    print(f"Variant {variant_id} results saved:")
    print(f"  Result: {result_file}")
    print(f"  Traces: {trace_file} ({len(traces)} traces)")

    return result_file, trace_file


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Enhanced consistency checker evaluation with trace export support"
    )
    parser.add_argument("--exercise", "-e", required=True, help="Exercise to evaluate")
    parser.add_argument(
        "--variant", "-v", help="Specific variant ID to evaluate (e.g., '001')"
    )
    parser.add_argument(
        "--all-variants",
        action="store_true",
        help="Evaluate all variants of the exercise",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="consistency_output.json",
        help="Output file name (for base exercise only)",
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
    parser.add_argument(
        "--no-traces",
        action="store_true",
        help="Disable trace export to improve performance",
    )

    args = parser.parse_args()

    # Convert language string to enum if provided
    programming_language = None
    if args.language:
        # Import here to avoid import issues
        from app.creation_steps.step8_review_and_refine.consistency_check.models import (
            ProgrammingLanguage,
        )

        programming_language = ProgrammingLanguage(args.language)

    try:
        if args.all_variants:
            # Evaluate all variants
            print(f"Evaluating all variants for exercise: {args.exercise}")
            variants = get_all_variants(args.exercise)

            if not variants:
                print(f"No variants found for exercise: {args.exercise}")
                return 0

            print(f"Found {len(variants)} variants: {', '.join(variants)}")

            for variant_id in variants:
                print(f"\n--- Evaluating variant {variant_id} ---")
                try:
                    evaluate_variant(
                        args.exercise, variant_id, args.model_name, programming_language
                    )
                except Exception as e:
                    print(f"Error evaluating variant {variant_id}: {e}")
                    continue

            print(f"\nCompleted evaluation of {len(variants)} variants")

        elif args.variant:
            # Evaluate specific variant
            print(f"Evaluating variant {args.variant} for exercise: {args.exercise}")
            evaluate_variant(
                args.exercise, args.variant, args.model_name, programming_language
            )

        else:
            # Evaluate base exercise (backward compatibility)
            print(f"Evaluating base exercise: {args.exercise}")
            result, traces, run_id = evaluate_exercise(
                args.exercise,
                model_name=args.model_name,
                programming_language=programming_language,
                export_traces=not args.no_traces,
            )

            # Save result (legacy format for compatibility)
            output_dir = Path(__file__).parent / "consistency_results"
            output_dir.mkdir(exist_ok=True)
            output_file = output_dir / args.output

            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)

            # Save traces if available
            if traces and not args.no_traces:
                trace_file = output_dir / f"consistency_traces_{run_id}.json"
                trace_data = {
                    "run_id": run_id,
                    "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
                    "commit_id": result.get("commit_id"),  # Include commit ID
                    "trace_count": len(traces),
                    "traces": traces,
                }
                with open(trace_file, "w", encoding="utf-8") as f:
                    json.dump(trace_data, f, indent=2, ensure_ascii=False)
                print(f"Traces saved to: {trace_file}")

            print(f"Found {len(result['response']['issues'])} issues")
            print(f"Result saved to: {output_file}")

    except Exception as e:
        print(f"Error: {e}")
        if os.environ.get("DEBUG"):
            traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
