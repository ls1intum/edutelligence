#!/usr/bin/env python
"""
Re-export LangSmith traces from existing result files without running consistency checks again.

Usage:
    cd hyperion
    # Re-export traces for all variants of an exercise
    python playground/reexport_traces.py --exercise "ITP2425/H05E01-Space_Seal_Farm"
    
    # Re-export traces for a specific variant
    python playground/reexport_traces.py --exercise "ITP2425/H05E01-Space_Seal_Farm" --variant "001"
"""

import sys
import json
import argparse
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

# Import LangSmith client for trace export
try:
    from langsmith import Client as LangSmithClient
    LANGSMITH_AVAILABLE = True
except ImportError:
    LANGSMITH_AVAILABLE = False
    print("Warning: LangSmith not available. Trace export will be disabled.")


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

        # Query runs from LangSmith using the specific trace ID with timeout
        import signal
        
        def timeout_handler(signum, frame):
            raise TimeoutError("LangSmith query timed out")
        
        # Set a 30-second timeout
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(30)
        
        try:
            runs = list(
                client.list_runs(
                    project_name=project_name,
                    trace_id=trace_id,
                    limit=100,  # Should be enough for one trace
                )
            )
            signal.alarm(0)  # Cancel timeout
        except TimeoutError:
            print(f"  ✗ Timeout querying LangSmith for trace {trace_id}")
            return []

        print(f"Found {len(runs)} LangSmith runs for trace {trace_id}")

        # Convert runs to serializable format
        traces = [json.loads(run.json()) for run in runs]
        print(f"Successfully exported {len(traces)} traces")

        # Print debug info about what we found
        if traces:
            print("Trace runs found:")
            for trace in traces[:3]:  # Limit to first 3 for brevity
                print(
                    f"  - {trace.get('name', 'No name')} ({trace.get('run_type', 'unknown')})"
                )
            if len(traces) > 3:
                print(f"  ... and {len(traces) - 3} more")

        return traces

    except Exception as e:
        print(f"Error exporting LangSmith traces: {e}")
        if os.environ.get("DEBUG"):
            import traceback
            traceback.print_exc()
        return []


def create_trace_file(
    result_data: Dict[str, Any], traces: List[Dict[str, Any]], result_file_path: Path
) -> tuple[Path, Optional[Path]]:
    """Create trace file with matching timestamp from result file and optional stats file."""
    # Extract original timestamp and run_id from result file name
    # Format: YYYYMMDD_HHMMSS_runid_result.json -> YYYYMMDD_HHMMSS_runid_trace.json
    result_filename = result_file_path.stem  # Remove .json
    if result_filename.endswith("_result"):
        base_name = result_filename[:-7]  # Remove "_result"
        trace_filename = f"{base_name}_trace.json"
        stats_filename = f"{base_name}_stats.json"
    else:
        # Fallback - just replace "result" with "trace"
        trace_filename = result_filename.replace("_result", "_trace") + ".json"
        stats_filename = result_filename.replace("_result", "_stats") + ".json"
    
    output_dir = result_file_path.parent
    trace_file = output_dir / trace_filename
    stats_file = output_dir / stats_filename
    
    # Create trace file
    run_id = result_data.get("run_id", "unknown")
    trace_data = {
        "run_id": run_id,
        "timestamp": result_data.get("timestamp", datetime.now().isoformat()),
        "commit_id": result_data.get("commit_id"),
        "trace_count": len(traces),
        "traces": traces,
    }
    
    with open(trace_file, "w", encoding="utf-8") as f:
        json.dump(trace_data, f, indent=2, ensure_ascii=False)

    # Create stats file from traces
    stats_file_created = None
    if traces:
        # Find the main consistency_check run
        consistency_check_run = None
        for trace in traces:
            if trace.get("name") == "consistency_check":
                consistency_check_run = trace
                break
        
        if consistency_check_run:
            try:
                from dateutil.parser import parse as parse_datetime
                
                def calculate_duration(start_time: str, end_time: str) -> float:
                    try:
                        start = parse_datetime(start_time)
                        end = parse_datetime(end_time)
                        return (end - start).total_seconds()
                    except Exception:
                        return 0.0
                
                # Extract statistics
                start_time = consistency_check_run.get("start_time", "")
                end_time = consistency_check_run.get("end_time", "")
                duration = calculate_duration(start_time, end_time)
                
                stats = {
                    "run_id": run_id,
                    "timestamp": result_data.get("timestamp", ""),
                    "commit_id": result_data.get("commit_id"),
                    "trace_id": consistency_check_run.get("trace_id", ""),
                    "start_time": start_time,
                    "end_time": end_time,
                    "duration": round(duration, 3),
                    "prompt_tokens": consistency_check_run.get("prompt_tokens", 0),
                    "completion_tokens": consistency_check_run.get("completion_tokens", 0),
                    "total_tokens": consistency_check_run.get("total_tokens", 0),
                    "total_cost": round(consistency_check_run.get("total_cost", 0.0), 6),
                    "prompt_cost": round(consistency_check_run.get("prompt_cost", 0.0), 6),
                    "completion_cost": round(consistency_check_run.get("completion_cost", 0.0), 6),
                }
                
                with open(stats_file, "w", encoding="utf-8") as f:
                    json.dump(stats, f, indent=2, ensure_ascii=False)
                
                stats_file_created = stats_file
                
            except ImportError:
                print("Warning: dateutil not available, skipping stats file creation")
            except Exception as e:
                print(f"Warning: Error creating stats file: {e}")

    return trace_file, stats_file_created


def process_result_file(result_file_path: Path) -> bool:
    """
    Process a single result file and re-export its traces.
    
    Returns:
        True if successful, False otherwise
    """
    try:
        print(f"\nProcessing: {result_file_path}")
        
        # Load result file
        with open(result_file_path, "r", encoding="utf-8") as f:
            result_data = json.load(f)
        
        # Extract trace ID
        trace_id = result_data.get("langsmith_trace_id")
        if not trace_id:
            print(f"  No trace ID found in {result_file_path}")
            return False
        
        print(f"  Found trace ID: {trace_id}")
        
        # Export traces
        traces = export_langsmith_traces(trace_id)
        
        if not traces:
            print(f"  No traces exported for {trace_id}")
            return False
        
        # Create new trace file
        trace_file, stats_file = create_trace_file(result_data, traces, result_file_path)
        
        print(f"  ✓ Exported {len(traces)} traces to: {trace_file}")
        if stats_file:
            print(f"  ✓ Created stats file: {stats_file}")
        return True
        
    except Exception as e:
        print(f"  ✗ Error processing {result_file_path}: {e}")
        return False


def find_result_files(exercise_path: str, variant_id: Optional[str] = None) -> List[Path]:
    """Find all result files for the given exercise and optionally specific variant."""
    base_path = Path(__file__).parent.parent / "data" / exercise_path
    result_files = []
    
    if variant_id:
        # Process specific variant
        variant_dir = base_path / "variants" / variant_id / "outputs"
        if variant_dir.exists():
            pattern = "*_result.json"
            result_files.extend(variant_dir.glob(pattern))
    else:
        # Process all variants
        variants_dir = base_path / "variants"
        if variants_dir.exists():
            pattern = "*/outputs/*_result.json"
            result_files.extend(variants_dir.glob(pattern))
    
    return sorted(result_files)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Re-export LangSmith traces from existing result files"
    )
    parser.add_argument("--exercise", "-e", required=True, help="Exercise to process")
    parser.add_argument(
        "--variant", "-v", help="Specific variant ID to process (e.g., '001')"
    )
    
    args = parser.parse_args()
    
    try:
        # Find result files
        result_files = find_result_files(args.exercise, args.variant)
        
        if not result_files:
            print(f"No result files found for exercise: {args.exercise}")
            if args.variant:
                print(f"Variant: {args.variant}")
            return 1
        
        print(f"Found {len(result_files)} result files to process")
        
        # Process each result file
        success_count = 0
        for result_file in result_files:
            if process_result_file(result_file):
                success_count += 1
        
        print(f"\n✓ Successfully re-exported traces for {success_count}/{len(result_files)} files")
        
        if success_count < len(result_files):
            print(f"✗ Failed to process {len(result_files) - success_count} files")
            return 1
        
        return 0
        
    except Exception as e:
        print(f"Error: {e}")
        if os.environ.get("DEBUG"):
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
