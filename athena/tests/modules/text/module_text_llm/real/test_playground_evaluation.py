import json
import pytest
from typing import List, Dict, Any, Tuple
from pathlib import Path

from athena.text import Exercise, Submission, Feedback
from athena.schemas.exercise_type import ExerciseType
from athena.schemas.text_submission import TextLanguageEnum
from module_text_llm.basic_approach.generate_suggestions import generate_suggestions
from module_text_llm.basic_approach import BasicApproachConfig
from module_text_llm.evaluation import get_feedback_statistics

# Import BERTScore for semantic similarity
try:
    from bert_score import score
    BERTSCORE_AVAILABLE = True
except ImportError:
    BERTSCORE_AVAILABLE = False
    print("Warning: BERTScore not available. Install with: pip install bert-score")


class PlaygroundEvaluator:
    """Helper class to evaluate LLM performance against playground ground truth."""
    
    def __init__(self, data_dir: str = None):
        if data_dir is None:
            self.data_dir = Path(__file__).parent.parent.parent.parent.parent.parent / "playground" / "data" / "example"
        else:
            self.data_dir = Path(data_dir)
    
    def load_exercise_with_tutor_feedback(self, exercise_id: int) -> Tuple[Exercise, List[Tuple[Submission, List[Feedback]]]]:
        """Load exercise and its submissions with tutor feedback."""
        exercise_file = self.data_dir / f"exercise-{exercise_id}.json"
        if not exercise_file.exists():
            raise FileNotFoundError(f"Exercise file not found: {exercise_file}")
        
        with open(exercise_file, 'r', encoding='utf-8') as f:
            exercise_data = json.load(f)
        
        # Convert to Athena Exercise
        exercise = Exercise(
            id=exercise_data["id"],
            title=exercise_data["title"],
            type=ExerciseType(exercise_data["type"]),
            max_points=exercise_data["max_points"],
            bonus_points=exercise_data.get("bonus_points", 0),
            grading_instructions=exercise_data.get("grading_instructions", ""),
            problem_statement=exercise_data.get("problem_statement", ""),
            example_solution=exercise_data.get("example_solution", ""),
            grading_criteria=[],
            meta=exercise_data.get("meta", {}),
        )
        
        # Convert submissions with ground truth feedback
        submissions_with_feedback = []
        for submission_data in exercise_data["submissions"]:
            submission = Submission(
                id=submission_data["id"],
                exercise_id=exercise.id,
                text=submission_data.get("text", ""),
                meta=submission_data.get("meta", {}),
                language=TextLanguageEnum.ENGLISH,
            )
            
            # Convert tutor feedback
            tutor_feedbacks = []
            for feedback_data in submission_data.get("feedbacks", []):
                feedback = Feedback(
                    exercise_id=exercise.id,
                    submission_id=submission.id,
                    title=feedback_data.get("title", ""),
                    description=feedback_data.get("description", ""),
                    index_start=feedback_data.get("index_start"),
                    index_end=feedback_data.get("index_end"),
                    credits=feedback_data.get("credits", 0.0),
                    is_graded=True,
                    structured_grading_instruction_id=feedback_data.get("structured_grading_instruction_id"),
                    meta=feedback_data.get("meta", {}),
                )
                tutor_feedbacks.append(feedback)
            
            submissions_with_feedback.append((submission, tutor_feedbacks))
        
        return exercise, submissions_with_feedback
    
    def calculate_evaluation_metrics(self, tutor_feedbacks: List[Feedback], predicted_feedbacks: List[Feedback]) -> Dict[str, Any]:
        """Calculate evaluation metrics comparing tutor vs predicted feedback."""
        
        # Basic statistics
        tutor_count = len(tutor_feedbacks)
        predicted_count = len(predicted_feedbacks)
        
        # Calculate overlap in feedback content (simple text similarity)
        tutor_descriptions = [f.description.lower() for f in tutor_feedbacks]
        predicted_descriptions = [f.description.lower() for f in predicted_feedbacks]
        
        # Simple keyword matching
        tutor_keywords = set()
        for desc in tutor_descriptions:
            tutor_keywords.update(desc.split())
        
        predicted_keywords = set()
        for desc in predicted_descriptions:
            predicted_keywords.update(desc.split())
        
        keyword_overlap = len(tutor_keywords.intersection(predicted_keywords))
        keyword_union = len(tutor_keywords.union(predicted_keywords))
        keyword_similarity = keyword_overlap / keyword_union if keyword_union > 0 else 0
        
        # BERTScore semantic similarity
        bert_score_similarity = 0.0
        if BERTSCORE_AVAILABLE and tutor_descriptions and predicted_descriptions:
            try:
                # Combine all tutor feedback into one text
                tutor_text = " ".join(tutor_descriptions)
                # Combine all predicted feedback into one text
                predicted_text = " ".join(predicted_descriptions)
                
                # Calculate BERTScore
                P, R, F1 = score([predicted_text], [tutor_text], lang='en', verbose=False)
                bert_score_similarity = F1.mean().item()  # Use F1 score as similarity metric
            except Exception as e:
                print(f"BERTScore calculation failed: {e}")
                bert_score_similarity = 0.0
        
        # Credit distribution analysis
        tutor_credits = [f.credits for f in tutor_feedbacks]
        predicted_credits = [f.credits for f in predicted_feedbacks]
        
        tutor_positive_count = len([c for c in tutor_credits if c > 0])
        tutor_negative_count = len([c for c in tutor_credits if c < 0])
        predicted_positive_count = len([c for c in predicted_credits if c > 0])
        predicted_negative_count = len([c for c in predicted_credits if c < 0])
        
        return {
            "tutor_feedback_count": tutor_count,
            "predicted_feedback_count": predicted_count,
            "keyword_similarity": keyword_similarity,
            "bert_score_similarity": bert_score_similarity,
            "tutor_positive_count": tutor_positive_count,
            "tutor_negative_count": tutor_negative_count,
            "predicted_positive_count": predicted_positive_count,
            "predicted_negative_count": predicted_negative_count,
            "tutor_total_credits": sum(tutor_credits),
            "predicted_total_credits": sum(predicted_credits),
            "credit_difference": abs(sum(tutor_credits) - sum(predicted_credits)),
            "credit_difference_percentage": (abs(sum(tutor_credits) - sum(predicted_credits)) / max(abs(sum(tutor_credits)), 1)) * 100,
        }


@pytest.fixture
def playground_evaluator():
    """Fixture to provide a playground evaluator."""
    return PlaygroundEvaluator()


@pytest.mark.asyncio
async def test_playground_exercise_7_evaluation(real_config, playground_evaluator):
    """Evaluate LLM performance on exercise 7 (SOLID principles) with ground truth."""
    
    # Load exercise with tutor feedback
    exercise, submissions_with_feedback = playground_evaluator.load_exercise_with_tutor_feedback(7)
    
    # For exercise 7, we'll test all submissions since it's a SOLID principles question
    # and we can evaluate the quality of feedback even without ground truth
    
    print(f"\n=== Exercise 7 Evaluation ===")
    print(f"Exercise: {exercise.title}")
    print(f"Total submissions: {len(submissions_with_feedback)}")
    
    # Test a subset of submissions for performance
    test_submissions = submissions_with_feedback[:10]  # First 10 submissions
    
    all_results = []
    
    for submission, tutor_feedbacks in test_submissions:
        # Generate LLM feedback
        predicted_feedbacks = await generate_suggestions(
            exercise=exercise,
            submission=submission,
            config=real_config,
            debug=False,
            is_graded=True,
        )
        
        # Analyze feedback quality
        feedback_analysis = {
            "submission_id": submission.id,
            "submission_text": submission.text[:100] + "..." if len(submission.text) > 100 else submission.text,
            "predicted_feedback_count": len(predicted_feedbacks),
            "tutor_feedback_count": len(tutor_feedbacks),
            "predicted_credits": sum(f.credits for f in predicted_feedbacks),
            "tutor_credits": sum(f.credits for f in tutor_feedbacks),
        }
        
        # Analyze feedback content
        all_feedback_text = " ".join([f.description.lower() for f in predicted_feedbacks])
        
        # Check for SOLID principles-related keywords
        solid_keywords = ["solid", "principle", "responsibility", "interface", "dependency", "design", "maintainable", "extensible"]
        found_keywords = [kw for kw in solid_keywords if kw in all_feedback_text]
        feedback_analysis["solid_keywords_found"] = len(found_keywords)
        feedback_analysis["solid_keywords_total"] = len(solid_keywords)
        
        all_results.append(feedback_analysis)
        
        print(f"Submission {submission.id}: "
              f"Predicted feedbacks: {len(predicted_feedbacks)}, "
              f"SOLID keywords: {len(found_keywords)}/{len(solid_keywords)}, "
              f"Credits: {feedback_analysis['predicted_credits']:.1f}")
    
    # Overall analysis
    if all_results:
        avg_feedback_count = sum(r["predicted_feedback_count"] for r in all_results) / len(all_results)
        avg_solid_keywords = sum(r["solid_keywords_found"] for r in all_results) / len(all_results)
        
        print(f"\nOverall Analysis:")
        print(f"Average feedback count: {avg_feedback_count:.1f}")
        print(f"Average SOLID keywords found: {avg_solid_keywords:.1f}/{len(solid_keywords)}")
        
        # Assertions
        assert avg_feedback_count > 0, "Should generate feedback for most submissions"
        assert avg_solid_keywords > 0, "Should mention SOLID principles concepts"


@pytest.mark.asyncio
async def test_playground_feedback_statistics(real_config, playground_evaluator):
    """Test the feedback statistics functionality with playground data."""
    
    # Load exercise 7 (has tutor feedback)
    exercise, submissions_with_feedback = playground_evaluator.load_exercise_with_tutor_feedback(7)
    
    # Find a submission with tutor feedback
    submission_with_tutor_feedback = None
    for submission, feedbacks in submissions_with_feedback:
        if feedbacks:
            submission_with_tutor_feedback = (submission, feedbacks)
            break
    
    if submission_with_tutor_feedback:
        submission, tutor_feedbacks = submission_with_tutor_feedback
        
        # Generate predicted feedback
        predicted_feedbacks = await generate_suggestions(
            exercise=exercise,
            submission=submission,
            config=real_config,
            debug=False,
            is_graded=True,
        )
        
        # Calculate feedback statistics
        stats = get_feedback_statistics(exercise, ground_truth_feedbacks, predicted_feedbacks)
        
        print(f"\n=== Feedback Statistics ===")
        print(f"Exercise: {exercise.title}")
        print(f"Submission: {submission.id}")
        print(f"Tutor feedbacks: {stats['actual_feedback_count']}")
        print(f"Predicted feedbacks: {stats['suggestions_count']}")
        print(f"Matched feedbacks: {stats['matched_feedback']}")
        print(f"Unmatched feedbacks: {stats['unmatched_feedback']}")
        print(f"Unmatched suggestions: {stats['unmatched_suggestions']}")
        
        # Assertions
        assert stats["actual_feedback_count"] > 0, "Should have tutor feedback"
        assert stats["suggestions_count"] >= 0, "Should have non-negative predicted feedback count"
        assert stats["matched_feedback"] >= 0, "Should have non-negative matched feedback count"


@pytest.mark.asyncio
async def test_playground_comprehensive_evaluation(real_config, playground_evaluator):
    """Comprehensive evaluation across multiple exercises."""
    
    # Test multiple exercises
    exercises_to_test = [7]  # SOLID principles question
    
    comprehensive_results = {}
    
    for exercise_id in exercises_to_test:
        try:
            exercise, submissions_with_feedback = playground_evaluator.load_exercise_with_tutor_feedback(exercise_id)
            
            print(f"\n=== Comprehensive Evaluation for Exercise {exercise_id} ===")
            print(f"Exercise: {exercise.title}")
            print(f"Total submissions: {len(submissions_with_feedback)}")
            
            exercise_results = {
                "exercise_id": exercise_id,
                "exercise_title": exercise.title,
                "total_submissions": len(submissions_with_feedback),
                "submissions_with_tutor_feedback": len([s for s, f in submissions_with_feedback if f]),
                "evaluated_submissions": 0,
                "total_predicted_feedbacks": 0,
                "total_tutor_feedbacks": 0,
                "average_keyword_similarity": 0.0,
                "average_bert_score": 0.0,
                "average_credit_difference": 0.0,
                "average_credit_difference_percentage": 0.0,
            }
            
            # Evaluate submissions with ground truth
            similarities = []
            bert_scores = []
            credit_differences = []
            credit_difference_percentages = []
            
            for submission, tutor_feedbacks in submissions_with_feedback:
                if tutor_feedbacks:  # Only evaluate submissions with tutor feedback
                    predicted_feedbacks = await generate_suggestions(
                        exercise=exercise,
                        submission=submission,
                        config=real_config,
                        debug=False,
                        is_graded=True,
                    )
                    
                    metrics = playground_evaluator.calculate_evaluation_metrics(
                        tutor_feedbacks, predicted_feedbacks
                    )
                    
                    similarities.append(metrics["keyword_similarity"])
                    bert_scores.append(metrics["bert_score_similarity"])
                    credit_differences.append(metrics["credit_difference"])
                    credit_difference_percentages.append(metrics["credit_difference_percentage"])
                    
                    exercise_results["evaluated_submissions"] += 1
                    exercise_results["total_predicted_feedbacks"] += len(predicted_feedbacks)
                    exercise_results["total_tutor_feedbacks"] += len(tutor_feedbacks)
            
            # Calculate averages
            if similarities:
                exercise_results["average_keyword_similarity"] = sum(similarities) / len(similarities)
                exercise_results["average_bert_score"] = sum(bert_scores) / len(bert_scores)
                exercise_results["average_credit_difference"] = sum(credit_differences) / len(credit_differences)
                exercise_results["average_credit_difference_percentage"] = sum(credit_difference_percentages) / len(credit_difference_percentages)
            
            comprehensive_results[exercise_id] = exercise_results
            
            print(f"Evaluated submissions: {exercise_results['evaluated_submissions']}")
            print(f"Average keyword similarity: {exercise_results['average_keyword_similarity']:.3f}")
            print(f"Average BERTScore: {exercise_results['average_bert_score']:.3f}")
            print(f"Average credit difference: {exercise_results['average_credit_difference']:.2f} ({exercise_results['average_credit_difference_percentage']:.1f}%)")
            
        except FileNotFoundError:
            print(f"Exercise {exercise_id} not found, skipping...")
            continue
    
    # Overall summary
    print(f"\n=== Comprehensive Evaluation Summary ===")
    for exercise_id, results in comprehensive_results.items():
        print(f"Exercise {exercise_id} ({results['exercise_title']}):")
        print(f"  - Evaluated: {results['evaluated_submissions']}/{results['submissions_with_tutor_feedback']} submissions")
        print(f"  - Avg keyword similarity: {results['average_keyword_similarity']:.3f}")
        print(f"  - Avg BERTScore: {results['average_bert_score']:.3f}")
        print(f"  - Avg credit difference: {results['average_credit_difference']:.2f} ({results['average_credit_difference_percentage']:.1f}%)")
    
    # Assertions
    assert len(comprehensive_results) > 0, "Should have evaluated at least one exercise"
    
    # Check that we have some evaluation results
    total_evaluated = sum(r["evaluated_submissions"] for r in comprehensive_results.values())
    assert total_evaluated > 0, "Should have evaluated at least one submission"


if __name__ == "__main__":
    # This allows running the tests directly for debugging
    pytest.main([__file__, "-v"]) 