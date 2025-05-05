import yaml
from pathlib import Path
from typing import List, Optional, Dict
from eval.models.schemas.external.llm_costs_config import LLMCostsConfig
from eval.models.schemas.external.structured_grading_instructions import Criterion, Instruction, StructuredGradingInstructions
from eval.models.schemas.internal.exercise import Exercise
from eval.models.schemas.internal.scenario_test_case import ScenarioTestCase
from eval.models.entities.scenario import Scenario
from eval.core.scenario_evaluation import evaluate_scenario
from eval.reporting.output_scenario_reports import output_results
from eval.utils.load_llm_cost_config import load_llm_cost_config
from eval.utils.filter_scenarios import filter_scenarios
from eval.utils.llm_cost_calculator import LLMCostCalculator


class EvaluationRunner:
    """
    The EvaluationRunner is responsible for orchestrating the entire evaluation process:
    - Loading a global LLM cost configuration from a specified path.
    - Identifying and loading scenarios from a directory structure.
    - Converting textual IDs to numeric IDs for criteria and instructions.
    - Running the evaluation pipeline (fetching feedback, scoring, computing costs).
    - Writing and aggregating scenario-level reports.
    """

    def __init__(self, 
                 scenarios_dir: Path, 
                 llm_cost_file: Path, 
                 run_name: Optional[str] = None):
        self.scenarios_dir = scenarios_dir
        self.llm_cost_file = llm_cost_file
        self.run_name = run_name

        self.llm_cost_config: Optional[LLMCostsConfig] = None
        self.llm_cost_calculator: Optional[LLMCostCalculator] = None

    def run_evaluation(self, max_tests: Optional[int], test_files: Optional[List[str]]):
        """
        Execute the full evaluation pipeline:
        - Load global LLM cost configuration.
        - Load all scenarios from the directory.
        - Filter scenarios based on user input (max_tests, test_files).
        - Evaluate each scenario and produce results.
        
        Args:
            max_tests (int or None): Maximum number of test cases to run per scenario.
            test_files (List[str] or None): Specific test files to run, overrides max_tests if provided.
        """
        self._load_global_llm_costs()
        scenarios = self._load_scenarios()
        
        # Filter scenarios
        scenarios = filter_scenarios(scenarios, max_tests, test_files)

        # Evaluate and output results
        self._evaluate_and_report_scenarios(scenarios)

    def _load_global_llm_costs(self):
        self.llm_cost_config = load_llm_cost_config(self.llm_cost_file.parent)
        self.llm_cost_calculator = LLMCostCalculator(self.llm_cost_config)

    def _load_scenarios(self) -> List[Scenario]:
        scenarios = []
        for scenario_dir in self.scenarios_dir.iterdir():
            if scenario_dir.is_dir():
                scenario = self._build_scenario(scenario_dir)
                if scenario:
                    scenarios.append(scenario)
        return scenarios

    def _build_scenario(self, scenario_dir: Path) -> Optional[Scenario]:
        manifest_path = scenario_dir / "manifest.yml"
        if not manifest_path.exists():
            print(f"Skipping scenario directory {scenario_dir} due to missing manifest.yml")
            return None

        manifest = self._load_manifest(manifest_path)

        # Process the manifest to build exercise and convert textual IDs
        exercise, default_expected, test_case_diffs = self._create_exercise_from_manifest(manifest, scenario_dir)

        test_cases = self._load_test_cases(scenario_dir / "test_cases")

        scenario = Scenario(
            server_url=manifest["server_url"],
            exercise=exercise,
            default_expected=default_expected,
            test_case_diffs=test_case_diffs,
            test_cases=test_cases
        )

        # Inject the global cost calculator
        scenario.llm_cost_calculator = self.llm_cost_calculator
        scenario.run_name = self.run_name

        return scenario

    def _load_manifest(self, manifest_path: Path) -> dict:
        with manifest_path.open("r", encoding="utf-8") as f:
            manifest = yaml.safe_load(f)
        return manifest

    def _create_exercise_from_manifest(self, manifest: dict, scenario_dir: Path):
        exercise_data = manifest["exercise"]

        # Extract criteria from the root level of the manifest
        criteria_data = manifest["criteria"]

        # 1. Convert textual criteria IDs to numeric IDs
        criteria_text_ids = [c_data["id"] for c_data in criteria_data]
        criteria_id_map = {}
        next_criteria_id = 1
        for ct_id in criteria_text_ids:
            criteria_id_map[ct_id] = next_criteria_id
            next_criteria_id += 1

        # 2. Convert textual instruction IDs to numeric IDs
        textual_ids = [instr_data["id"] for c_data in criteria_data for instr_data in c_data["instructions"]]
        instruction_id_map = {}
        next_id = 1
        for t_id in textual_ids:
            instruction_id_map[t_id] = next_id
            next_id += 1

        # Convert instructions and criteria to structured objects with numeric IDs
        converted_criteria: StructuredGradingInstructions = []
        for c_data in criteria_data:
            converted_instructions = []
            for instr_data in c_data["instructions"]:
                original_text_id = instr_data["id"]
                new_integer_id = instruction_id_map[original_text_id]
                instr_data["id"] = new_integer_id
                instr_data["meta"] = {"textual_id": {new_integer_id: original_text_id}}
                # Set usage_count if not present
                if "usage_count" not in instr_data:
                    instr_data["usage_count"] = 1
                converted_instructions.append(Instruction(**instr_data))

            original_text_id = c_data["id"]
            new_integer_id = criteria_id_map[original_text_id]
            criterion = Criterion(
                id=new_integer_id,
                title=c_data["title"],
                structured_grading_instructions=converted_instructions,
                meta={"textual_id": {new_integer_id: original_text_id}}
            )
            converted_criteria.append(criterion)

        # Convert default_expected and test_case_diffs from textual to numeric
        default_expected_text = manifest.get("default_expected", [])
        test_case_diffs_text = manifest.get("test_case_diffs", {})

        # Convert default_expected textual to numeric
        default_expected = [instruction_id_map[t_id] for t_id in default_expected_text]

        # Convert test_case_diffs textual to numeric
        test_case_diffs: Dict[int, Dict[str, int]] = {}
        for correct_t_id, cases_dict in test_case_diffs_text.items():
            correct_id = instruction_id_map[correct_t_id]
            test_case_diffs[correct_id] = {}
            for tc_name, new_t_id in cases_dict.items():
                test_case_diffs[correct_id][tc_name] = instruction_id_map[new_t_id]

        # Insert the processed criteria into the exercise_data
        exercise_data["grading_criteria"] = converted_criteria

        # If example_solution is a string (filename), load it
        if "example_solution" in exercise_data and isinstance(exercise_data["example_solution"], str):
            example_solution_path = scenario_dir / exercise_data["example_solution"]
            if example_solution_path.exists():
                with example_solution_path.open("r", encoding="utf-8") as f:
                    example_solution_data = f.read()
                exercise_data["example_solution"] = example_solution_data
            else:
                print(f"Warning: example solution file '{exercise_data['example_solution']}' not found in {scenario_dir}")

        exercise = Exercise(**exercise_data)

        return exercise, default_expected, test_case_diffs

    def _load_test_cases(self, test_cases_dir: Path):
        test_cases = []
        if test_cases_dir.exists():
            for tc_file in test_cases_dir.glob("*.json"):
                test_cases.append(ScenarioTestCase(name=tc_file.stem, file=str(tc_file)))
        return test_cases

    def _evaluate_and_report_scenarios(self, scenarios: List[Scenario]):
        for scenario in scenarios:
            scenario_result = evaluate_scenario(scenario)
            output_results(scenario, scenario_result)
