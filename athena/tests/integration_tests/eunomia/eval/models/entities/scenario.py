import os
from typing import List, Dict, Optional, Tuple
from eval.models.schemas.internal.exercise import Exercise
from eval.models.schemas.internal.scenario_test_case import ScenarioTestCase
from eval.utils.llm_cost_calculator import LLMCostCalculator

class Scenario:
    def __init__(
        self,
        server_url: str,
        exercise: Exercise,
        default_expected: List[int],
        test_case_diffs: Optional[Dict[int, Dict[str, int]]] = None,
        test_cases: Optional[List[ScenarioTestCase]] = None
    ):
        self.failed_tests_due_to_server: List[str] = []
        self.server_url = server_url
        self.exercise = exercise
        self.criteria = exercise.grading_criteria
        self.default_expected = default_expected
        self.test_case_diffs = test_case_diffs or {}
        self.test_cases = test_cases or []
        self.run_name: Optional[str] = None
        self.llm_cost_calculator : Optional[LLMCostCalculator] = None

        self.instr_id_to_textual_id = {}
        self.instr_id_to_description = {}

        for c in self.criteria:
            for instr in c.structured_grading_instructions:
                textual_id_dict = instr.meta.get("textual_id", {})
                textual_id = textual_id_dict.get(instr.id)
                if textual_id:
                    self.instr_id_to_textual_id[instr.id] = textual_id

                self.instr_id_to_description[instr.id] = instr.instruction_description

        self.instr_to_crit = {}
        self.instr_to_credits = {}
        for c in self.criteria:
            for instr in c.structured_grading_instructions:
                self.instr_to_crit[instr.id] = c.id
                self.instr_to_credits[instr.id] = instr.credits

        # Build a lookup from global_id to instruction credits
        self.global_id_to_credits = {}
        for c in self.criteria:
            for instr in c.structured_grading_instructions:
                self.global_id_to_credits[instr.id] = instr.credits

        self.criterion_id_to_textual_id = {}
        for c in self.criteria:
            self.criterion_id_to_textual_id[c.id] = c.meta.get("textual_id", {}).get(c.id, None)

        self.initialize_test_case_expectations()

    def compute_expected_for_test_case(self, test_case_name: str) -> Tuple[List[int], float]:
        # Start with default_expected
        expected_instructions = self.default_expected[:]

        # We have the default_expected structured grading instruction that we assume to be applied for the sample solution (perfect diagram). For each test case we change certain aspects of this perfect solution to see if the model correctly identifies the changes and applies a corresponding instruction. For each test case our expected instructions slightly differ. This difference is stored in test_case_diffs. Therefore we start with the default_expected and check which of our expected instructions differ and change them accordingly.
        for i, instr_id in enumerate(expected_instructions):
            if instr_id in self.test_case_diffs:
                if test_case_name in self.test_case_diffs[instr_id]:
                    expected_instructions[i] = self.test_case_diffs[instr_id][test_case_name]

        # Compute the total credits for the test case based on the sum of credits of the expected instructions
        total_score = sum(self.global_id_to_credits[i_id] for i_id in expected_instructions)

        return expected_instructions, total_score

    def initialize_test_case_expectations(self):
        for tc in self.test_cases:
            e_instructions, e_score = self.compute_expected_for_test_case(tc.name)
            tc.expected_instructions = e_instructions
            tc.expected_score = e_score

    def get_results_base_dir(self) -> str:
        scenario_title_dir = self.exercise.title.replace(" ", "_")
        if self.run_name:
            return os.path.join("results", self.run_name, scenario_title_dir)
        else:
            return os.path.join("results", scenario_title_dir)
