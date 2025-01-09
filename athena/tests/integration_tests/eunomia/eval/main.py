import sys
from eval.models.entities.evaluation_runner import EvaluationRunner
from pathlib import Path
from eval.utils.get_user_input import get_user_input

def main():
    # Get user input
    max_tests, test_files, run_name = get_user_input()

    # Construct absolute paths
    project_root = Path(__file__).parent.parent.resolve()  
    scenarios_dir = project_root / "scenarios"
    llm_cost_file = scenarios_dir / "llm_cost.yml"

    # Check if scenario directory and llm_cost.yml exist
    if not scenarios_dir.exists():
        print(f"Scenario directory not found at {scenarios_dir}")
        sys.exit(1)

    if not llm_cost_file.exists():
        print(f"llm_cost.yml not found at {llm_cost_file}")
        sys.exit(1)

    # Create and run the evaluation runner
    runner = EvaluationRunner(
        scenarios_dir=scenarios_dir,
        llm_cost_file=llm_cost_file,
        run_name=run_name
    )
    
    runner.run_evaluation(max_tests, test_files)

if __name__ == "__main__":
    main()