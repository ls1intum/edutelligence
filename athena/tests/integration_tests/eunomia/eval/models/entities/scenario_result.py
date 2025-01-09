from typing import Dict, List
from eval.models.entities.test_case_result import TestCaseResult

class ScenarioResult:
    def __init__(self, evaluation_results: List[TestCaseResult]):
        self.evaluation_results = evaluation_results
        self.total_cases = len(evaluation_results)
        self.fully_correct = sum(r.correct for r in evaluation_results)
        self.score_matched_count = sum(r.score_match for r in evaluation_results)
        self.missed_instruction_counts = self._compute_missed_instruction_counts(evaluation_results)

        # Compute additional metrics like test cases detected correctly
        self.test_case_detected_correctly_count = sum(1 for r in evaluation_results if r.test_case_detected_correctly)

        # Compute average test case score
        if self.total_cases > 0:
            self.average_test_case_score = sum(r.test_case_score_percent for r in evaluation_results) / self.total_cases
            self.average_request_time = sum(r.request_time for r in evaluation_results) / self.total_cases
        else:
            self.average_test_case_score = 0.0
            self.average_request_time = 0.0

        self.total_cost = self._compute_total_cost()
        self.average_cost = self.total_cost / self.total_cases if self.total_cases > 0 else 0.0

    def _compute_total_cost(self) -> float:
        total_cost = 0.0
        for r in self.evaluation_results:
            if r.case_costs is not None:
                total_cost += r.case_costs.total_usage.total_cost
        return total_cost

    def _compute_missed_instruction_counts(self, evaluation_results: List[TestCaseResult]) -> Dict[int, int]:
        counts = {}
        for r in evaluation_results:
            for instr_id in r.missing_instructions:
                counts[instr_id] = counts.get(instr_id, 0) + 1
        return counts

    def to_dict(self) -> Dict:
        return {
            "total_cases": self.total_cases,
            "fully_correct": self.fully_correct,
            "score_matched_count": self.score_matched_count,
            "missed_instruction_counts": self.missed_instruction_counts,
            "test_case_detected_correctly_count": self.test_case_detected_correctly_count,
            "average_test_case_score": self.average_test_case_score,
            "average_request_time_seconds": self.average_request_time
        }
