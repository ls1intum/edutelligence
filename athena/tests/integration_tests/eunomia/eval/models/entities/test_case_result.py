from typing import Dict, List, Tuple, Any, Optional, TypedDict
from eval.models.schemas.external.api_response import LLMUsage
from eval.models.schemas.external.feedback import ModelingFeedback
from eval.models.entities.scenario import Scenario
from eval.models.schemas.external.llm_costs_config import CaseCostResult
from eval.models.schemas.internal.scenario_test_case import ScenarioTestCase
from collections import defaultdict

FLOAT_TOLERANCE = 1e-6


class Mismatch(TypedDict):
    expected_instr_id: Optional[int]
    expected_crit_id: Optional[int]
    returned_instr_id: Optional[int]
    returned_crit_id: Optional[int]

class TestCaseResult:
    def __init__(
        self,
        scenario: Scenario,
        test_case: ScenarioTestCase,
        feedback: List[ModelingFeedback],
        llm_usage: LLMUsage,
        request_time: float
    ):
        self._scenario = scenario
        self.name: str = test_case.name
        self.expected_instructions: List[int] = test_case.expected_instructions or []
        self.expected_score: float = test_case.expected_score or 0.0
        self.request_time = request_time

        self.feedback: List[ModelingFeedback] = feedback
        self.llm_usage: LLMUsage = llm_usage

        self._initialize_computed_properties(scenario)

        self.case_costs: Optional[CaseCostResult] = None

        if scenario.llm_cost_calculator:
            self.case_costs = scenario.llm_cost_calculator.compute_case_costs(llm_usage)

    def _initialize_computed_properties(self, scenario: Any) -> None:
        """Initialize all computed metrics for this evaluation result."""
        self.feedback_info = self._prepare_feedback_info(scenario, self.feedback)

        self.returned_instructions = self._compute_returned_instructions(self.feedback_info)
        self.unrecognized_instructions = self._compute_unrecognized_instructions(self.feedback_info)
        self.returned_score = self._compute_returned_score(self.feedback_info)
        self.returned_score_including_unreferenced = self._compute_returned_score_including_unreferenced(self.feedback_info)

        self.missing_instructions = self._compute_missing_instructions()
        self.extra_instructions = self._compute_extra_instructions()
        self.correct = self._compute_correctness()
        self.score_match = self._compute_score_match()

        self.test_case_detected_correctly, self.test_case_score_percent = self._compute_test_case_detection_metrics(scenario)
        self.instructions_wrong_less, self.instructions_wrong_more = self._compute_point_discrepancies(scenario)

    def _prepare_feedback_info(
        self,
        scenario: Any,
        feedback: List[ModelingFeedback]
    ) -> List[Tuple[Optional[int], bool, float]]:
        """
        Process each feedback item and return a list of tuples:
        (global_id, recognized, credits).
        """
        return [
            (
                self._extract_global_id(fb_item),
                self._is_recognized_instruction(self._extract_global_id(fb_item), scenario),
                fb_item.credits,
            )
            for fb_item in feedback
        ]

    def _extract_global_id(self, feedback_item: ModelingFeedback) -> Optional[int]:
        """Extract the global instruction ID from a feedback item."""
        global_id = feedback_item.structured_grading_instruction_id
        return int(global_id) if global_id is not None else None

    def _is_recognized_instruction(self, global_id: Optional[int], scenario: Any) -> bool:
        """Determine if a given global_id is recognized within the scenario."""
        return global_id is not None and global_id in scenario.global_id_to_credits

    def _compute_returned_instructions(self, feedback_info: List[Tuple[Optional[int], bool, float]]) -> List[int]:
        """
        Compute the list of returned instructions from prepared feedback info.
        """
        return [
            global_id for global_id, recognized, _ in feedback_info
            if global_id is not None and recognized
        ]

    def _compute_unrecognized_instructions(self, feedback_info: List[Tuple[Optional[int], bool, float]]) -> List[int]:
        """
        Compute the list of unrecognized instructions from prepared feedback info.
        """
        return [
            global_id for global_id, recognized, _ in feedback_info
            if global_id is not None and not recognized
        ]

    def _compute_returned_score(self, feedback_info: List[Tuple[Optional[int], bool, float]]) -> float:
        """
        Compute the returned score (sum of credits for recognized instructions).
        """
        return sum(credits for _, recognized, credits in feedback_info if recognized)

    def _compute_returned_score_including_unreferenced(self, feedback_info: List[Tuple[Optional[int], bool, float]]) -> float:
        """
        Compute the returned score including unreferenced instructions (sum of all credits).
        """
        return sum(credits for _, _, credits in feedback_info)

    def _compute_missing_instructions(self) -> List[int]:
        """Compute the list of instructions expected but not returned."""
        return [instr for instr in self.expected_instructions if instr not in self.returned_instructions]

    def _compute_extra_instructions(self) -> List[int]:
        """Compute the list of instructions that are extra (returned but neither expected nor unrecognized)."""
        return [
            instr for instr in self.returned_instructions
            if instr not in self.expected_instructions and instr not in self.unrecognized_instructions
        ]

    def _compute_correctness(self) -> bool:
        """Check if all expected instructions are present and no unrecognized instructions are found."""
        return not self.missing_instructions and not self.unrecognized_instructions

    def _compute_score_match(self) -> bool:
        """Check if the returned score matches the expected score within a tolerance."""
        return abs(self.expected_score - self.returned_score) < FLOAT_TOLERANCE

    def _compute_test_case_detection_metrics(self, scenario: Any) -> Tuple[bool, float]:
        """
        Compute whether the test case was detected correctly and the weighted percentage score.
        """
        diff_instructions_for_tc = self._get_diff_instructions_for_test_case(scenario)
        total_weight, achieved_weight = self._compute_weighted_scores(diff_instructions_for_tc)
        test_case_detected_correctly = diff_instructions_for_tc.issubset(self.returned_instructions)
        test_case_score_percent = (achieved_weight / total_weight * 100.0) if total_weight > 0 else 0.0
        return test_case_detected_correctly, test_case_score_percent

    def _get_diff_instructions_for_test_case(self, scenario: Any) -> set:
        """
        Retrieve the set of diff instructions associated with this test case from the scenario.
        """
        diff_instructions_for_tc = {
            cases_dict[self.name]
            for correct_id, cases_dict in scenario.test_case_diffs.items()
            if self.name in cases_dict
        }
        return diff_instructions_for_tc

    def _compute_weighted_scores(self, diff_instructions_for_tc: set) -> Tuple[int, int]:
        """
        Compute the total and achieved weights for instructions,
        giving double weight to those in the diff_instructions_for_tc set.
        """
        total_weight = 0
        achieved_weight = 0
        for instr_id in self.expected_instructions:
            weight = 2 if instr_id in diff_instructions_for_tc else 1
            total_weight += weight
            if instr_id in self.returned_instructions:
                achieved_weight += weight
        return total_weight, achieved_weight

    def _compute_point_discrepancies(self, scenario: Any) -> Tuple[int, int]:
        """
        This function focuses on analyzing grading discrepancies at the level of criteria and their associated instructions. Each scenario criterion outlines a set of instructions, each with a certain point value, that represent the "ideal" solution for that criterion. If the student's submission deviates from these expectations, we want to determine in terms of gained or lost points relative to the ideal scenario.

        Logic:
        - Group missing and extra instructions by their criterion.
        - Pair a missing with an extra one-to-one. If returned credits > expected credits -> wrong_more else wrong_less.
        - Any leftover missing instructions -> wrong_less (lost points).
        - Any leftover extra instructions -> decide based on their credits. If >0 -> wrong_more, else wrong_less.
        """

        wrong_less = 0
        wrong_more = 0

        # Group instructions by criterion
        instructions_by_crit = defaultdict(lambda: {"missing": [], "extra": []})
        get_credits = scenario.instr_to_credits.get

        # Sort missing instructions into their respective criteria
        for instr_id in self.missing_instructions:
            crit_id = scenario.instr_to_crit.get(instr_id)
            if crit_id is None:
                # No criterion means we lost points expected somewhere, count as wrong_less
                wrong_less += 1
            else:
                instructions_by_crit[crit_id]["missing"].append(instr_id)

        # Sort extra instructions into their respective criteria
        for instr_id in self.extra_instructions:
            crit_id = scenario.instr_to_crit.get(instr_id)
            if crit_id is None:
                # No expected criterion; assume wrong_more if >0 credits, else wrong_less
                if get_credits(instr_id, 0) > 0:
                    wrong_more += 1
                else:
                    wrong_less += 1
            else:
                instructions_by_crit[crit_id]["extra"].append(instr_id)

        # Now pair them up criterion by criterion
        for crit_id, groups in instructions_by_crit.items():
            missing_list = groups["missing"]
            extra_list = groups["extra"]

            # Pair missing and extra one-to-one
            while missing_list and extra_list:
                expected_i = missing_list.pop()
                returned_i = extra_list.pop()

                exp_credits = get_credits(expected_i, 0)
                ret_credits = get_credits(returned_i, 0)
                if ret_credits > exp_credits:
                    wrong_more += 1
                else:
                    wrong_less += 1

            # Unpaired missing instructions: we lost these points
            wrong_less += len(missing_list)

            # Unpaired extra instructions: guess based on their credits
            for e_i in extra_list:
                if get_credits(e_i, 0) > 0:
                    wrong_more += 1
                else:
                    wrong_less += 1

        return wrong_less, wrong_more
    
    def _instr_details(self, instr_id: int, scenario: Any, received: bool) -> Dict[str, Any]:
        details = {
            "id": instr_id,
            "textual_id": scenario.instr_id_to_textual_id.get(instr_id),
            "credits": scenario.instr_to_credits.get(instr_id, 0.0),
            "instructionDescription": scenario.instr_id_to_description.get(instr_id)
        }

        # If the instruction was actually received, try to find the corresponding feedback from this test's results.
        if received:
            for fb in self.feedback:
                if fb.structured_grading_instruction_id == instr_id:
                    details["feedbackDescription"] = fb.description
                    break

        return details


    def _build_criteria_results(self, scenario: Any) -> Dict[str, Any]:
        """
        Build a structure that shows only the mismatches by criterion, plus any unmapped instructions.
        Uses "received" for instructions that were actually returned by the student's solution,
        and not for those that were only expected but not returned.
        """

        # Organize expected and returned instructions by criterion
        criterion_expected = {}
        criterion_returned = {}

        for instr_id in self.expected_instructions:
            crit_id = scenario.instr_to_crit.get(instr_id)
            if crit_id is not None:
                criterion_expected.setdefault(crit_id, set()).add(instr_id)

        for instr_id in self.returned_instructions:
            crit_id = scenario.instr_to_crit.get(instr_id)
            if crit_id is not None:
                criterion_returned.setdefault(crit_id, set()).add(instr_id)

        # Identify unmapped extra instructions
        all_returned = set(self.returned_instructions)
        all_expected = set(self.expected_instructions)
        truly_extra = all_returned - all_expected

        unmapped_instructions = []
        for instr_id in truly_extra:
            crit_id = scenario.instr_to_crit.get(instr_id)
            if crit_id is None:
                # Unmapped instructions were returned, so received=True
                unmapped_instructions.append(self._instr_details(instr_id, scenario, received=True))

        # Handle mismatches per criterion
        criteria_mismatches = []
        all_criteria = set(criterion_expected.keys()) | set(criterion_returned.keys())

        for crit_id in all_criteria:
            exp = criterion_expected.get(crit_id, set())
            ret = criterion_returned.get(crit_id, set())

            missing = exp - ret
            extra = ret - exp

            # Attempt to pair them one-to-one
            paired = []
            missing_list = sorted(missing)
            extra_list = sorted(extra)

            while missing_list and extra_list:
                m = missing_list.pop(0)
                e = extra_list.pop(0)
                paired.append((m, e))

            # Construct mismatch structure only if there is something to report
            if paired or missing_list or extra_list:
                crit_text_id = scenario.criterion_id_to_textual_id.get(crit_id)
                criterion_data = {
                    "criterion_id": crit_id,
                    "criterion_textual_id": crit_text_id,
                    "mismatch_pairs": [
                        {
                            # expected not received => received=False
                            "expected": self._instr_details(m, scenario, received=False),
                            # received was actually returned => received=True
                            "received": self._instr_details(e, scenario, received=True)
                        }
                        for (m, e) in paired
                    ],
                    # missing are expected but not received => received=False
                    "missing_instructions": [self._instr_details(m, scenario, received=False) for m in missing_list],
                    # extra are returned but not expected => received=True
                    "extra_instructions": [self._instr_details(e, scenario, received=True) for e in extra_list]
                }
                criteria_mismatches.append(criterion_data)

        result = {}
        if criteria_mismatches:
            result["criteria_results"] = criteria_mismatches
        if unmapped_instructions:
            result["unmapped_instructions"] = unmapped_instructions

        return result


    def to_dict(self) -> Dict:
        """
        Convert the test case result to a dictionary representation,
        focusing on mismatches and relevant feedback.
        """
        # Get mismatch data
        criteria_mismatch_data = self._build_criteria_results(self._scenario)

        # Basic fields
        result = {
            "test_case": self.name,
            "expected_score": self.expected_score,
            "returned_score": self.returned_score,
            "test_case_detected_correctly": self.test_case_detected_correctly,
            "test_case_score_percent": self.test_case_score_percent
        }

        if self.case_costs:
            # Convert typed model costs to dict
            cost_details = [
                {
                    "llm": m.model,
                    "input_cost": m.input_cost,
                    "output_cost": m.output_cost,
                    "total": m.total_cost
                }
                for m in self.case_costs.model_costs.values()
            ]
            result["cost"] = {
                "total_cost": self.case_costs.total_usage.total_cost,
                "total_input_cost": self.case_costs.total_usage.input_cost,
                "total_output_cost": self.case_costs.total_usage.output_cost,
                "details": cost_details
            }

        result.update(criteria_mismatch_data)
        result["feedback"] = [f.dict() for f in self.feedback]

        return result