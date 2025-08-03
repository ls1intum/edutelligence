#!/usr/bin/env python3
"""
Test runner for playground integration tests.

This script runs the playground integration tests and generates a comprehensive report
on how the LLM module performs on real exercises from the playground.
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Dict, List, Any
from datetime import datetime

# Add the module path to sys.path
module_path = Path(__file__).parent.parent.parent.parent.parent.parent
sys.path.insert(0, str(module_path))

from tests.modules.text.module_text_llm.real.test_playground_integration import PlaygroundExerciseLoader
from tests.modules.text.module_text_llm.real.test_playground_evaluation import PlaygroundEvaluator
from module_text_llm.basic_approach.generate_suggestions import generate_suggestions
from module_text_llm.basic_approach import BasicApproachConfig
from llm_core.models.providers.azure_model_config import AzureModelConfig

# Import BERTScore for semantic similarity
try:
    from bert_score import score
    BERTSCORE_AVAILABLE = True
except ImportError:
    BERTSCORE_AVAILABLE = False
    print("Warning: BERTScore not available. Install with: pip install bert-score")


class PlaygroundTestRunner:
    """Test runner for playground integration tests."""
    
    def __init__(self):
        self.loader = PlaygroundExerciseLoader()
        self.evaluator = PlaygroundEvaluator()
        self.config = BasicApproachConfig(
            max_input_tokens=5000,
            model=AzureModelConfig(
                model_name="azure_openai_gpt-4o",
                get_model=lambda: None,
            ),
            type="basic",
        )
        self.results = {}
    
    async def run_single_exercise_test(self, exercise_id: int) -> Dict[str, Any]:
        """Run tests for a single exercise."""
        print(f"\n{'='*60}")
        print(f"Testing Exercise {exercise_id}")
        print(f"{'='*60}")
        
        try:
            # Load exercise data
            exercise_data = self.loader.load_exercise(exercise_id)
            exercise = self.loader.convert_to_athena_exercise(exercise_data)
            
            print(f"Exercise: {exercise.title}")
            print(f"Type: {exercise.type}")
            print(f"Max points: {exercise.max_points}")
            print(f"Submissions: {len(exercise_data['submissions'])}")
            
            # Test a subset of submissions for performance
            test_submissions = exercise_data["submissions"][:5]  # First 5 submissions
            
            exercise_results = {
                "exercise_id": exercise_id,
                "exercise_title": exercise.title,
                "exercise_type": str(exercise.type),
                "max_points": exercise.max_points,
                "total_submissions": len(exercise_data["submissions"]),
                "tested_submissions": len(test_submissions),
                "submission_results": [],
                "performance_metrics": {},
            }
            
            for submission_data in test_submissions:
                submission = self.loader.convert_to_athena_submission(submission_data, exercise.id)
                
                print(f"\n  Testing submission {submission.id}: {submission.text[:50]}...")
                
                # Generate feedback
                feedbacks = await generate_suggestions(
                    exercise=exercise,
                    submission=submission,
                    config=self.config,
                    debug=False,
                    is_graded=True,
                )
                
                # Analyze feedback
                feedback_analysis = {
                    "submission_id": submission.id,
                    "submission_text": submission.text,
                    "feedback_count": len(feedbacks),
                    "total_credits": sum(f.credits for f in feedbacks),
                    "positive_feedback_count": len([f for f in feedbacks if f.credits > 0]),
                    "negative_feedback_count": len([f for f in feedbacks if f.credits < 0]),
                    "neutral_feedback_count": len([f for f in feedbacks if f.credits == 0]),
                    "feedback_descriptions": [f.description for f in feedbacks],
                }
                
                exercise_results["submission_results"].append(feedback_analysis)
                
                print(f"    Generated {len(feedbacks)} feedbacks")
                print(f"    Total credits: {feedback_analysis['total_credits']:.1f}")
                print(f"    Positive: {feedback_analysis['positive_feedback_count']}, "
                      f"Negative: {feedback_analysis['negative_feedback_count']}, "
                      f"Neutral: {feedback_analysis['neutral_feedback_count']}")
            
            # Calculate performance metrics
            if exercise_results["submission_results"]:
                total_feedbacks = sum(r["feedback_count"] for r in exercise_results["submission_results"])
                avg_feedbacks = total_feedbacks / len(exercise_results["submission_results"])
                avg_credits = sum(r["total_credits"] for r in exercise_results["submission_results"]) / len(exercise_results["submission_results"])
                
                exercise_results["performance_metrics"] = {
                    "average_feedback_count": avg_feedbacks,
                    "average_credits": avg_credits,
                    "total_feedbacks_generated": total_feedbacks,
                    "submissions_with_feedback": len([r for r in exercise_results["submission_results"] if r["feedback_count"] > 0]),
                }
                
                print(f"\n  Performance Summary:")
                print(f"    Average feedbacks per submission: {avg_feedbacks:.1f}")
                print(f"    Average credits per submission: {avg_credits:.1f}")
                print(f"    Submissions with feedback: {exercise_results['performance_metrics']['submissions_with_feedback']}/{len(exercise_results['submission_results'])}")
            
            return exercise_results
            
        except Exception as e:
            print(f"Error testing exercise {exercise_id}: {e}")
            return {
                "exercise_id": exercise_id,
                "error": str(e),
            }
    
    async def run_tutor_feedback_evaluation(self, exercise_id: int) -> Dict[str, Any]:
        """Run evaluation against tutor feedback."""
        print(f"\n{'='*60}")
        print(f"Tutor Feedback Evaluation for Exercise {exercise_id}")
        print(f"{'='*60}")
        
        try:
            exercise, submissions_with_feedback = self.evaluator.load_exercise_with_tutor_feedback(exercise_id)
            
            # Filter to submissions with tutor feedback
            submissions_with_tutor_feedback = [
                (submission, feedbacks) for submission, feedbacks in submissions_with_feedback 
                if feedbacks
            ]
            
            print(f"Exercise: {exercise.title}")
            print(f"Submissions with tutor feedback: {len(submissions_with_tutor_feedback)}")
            
            evaluation_results = {
                "exercise_id": exercise_id,
                "exercise_title": exercise.title,
                "submissions_evaluated": len(submissions_with_tutor_feedback),
                "evaluation_metrics": [],
            }
            
            for submission, tutor_feedbacks in submissions_with_tutor_feedback:
                print(f"\n  Evaluating submission {submission.id}")
                
                # Generate predicted feedback
                predicted_feedbacks = await generate_suggestions(
                    exercise=exercise,
                    submission=submission,
                    config=self.config,
                    debug=False,
                    is_graded=True,
                )
                
                # Calculate metrics
                metrics = self.evaluator.calculate_evaluation_metrics(
                    tutor_feedbacks, predicted_feedbacks
                )
                
                metrics["submission_id"] = submission.id
                evaluation_results["evaluation_metrics"].append(metrics)
                
                print(f"    Tutor feedbacks: {len(tutor_feedbacks)}")
                print(f"    Predicted feedbacks: {len(predicted_feedbacks)}")
                print(f"    Keyword similarity: {metrics['keyword_similarity']:.3f}")
                if BERTSCORE_AVAILABLE:
                    print(f"    BERTScore: {metrics['bert_score_similarity']:.3f}")
                print(f"    Credit difference: {metrics['credit_difference']:.2f} ({metrics['credit_difference_percentage']:.1f}%)")
            
            # Calculate overall metrics
            if evaluation_results["evaluation_metrics"]:
                avg_similarity = sum(m["keyword_similarity"] for m in evaluation_results["evaluation_metrics"]) / len(evaluation_results["evaluation_metrics"])
                avg_credit_diff = sum(m["credit_difference"] for m in evaluation_results["evaluation_metrics"]) / len(evaluation_results["evaluation_metrics"])
                
                evaluation_results["overall_metrics"] = {
                    "average_keyword_similarity": avg_similarity,
                    "average_credit_difference": avg_credit_diff,
                }
                
                print(f"\n  Overall Evaluation:")
                print(f"    Average keyword similarity: {avg_similarity:.3f}")
                
                if BERTSCORE_AVAILABLE:
                    avg_bert_score = sum(m["bert_score_similarity"] for m in evaluation_results["evaluation_metrics"]) / len(evaluation_results["evaluation_metrics"])
                    evaluation_results["overall_metrics"]["average_bert_score"] = avg_bert_score
                    print(f"    Average BERTScore: {avg_bert_score:.3f}")
                
                avg_credit_diff_percentage = sum(m["credit_difference_percentage"] for m in evaluation_results["evaluation_metrics"]) / len(evaluation_results["evaluation_metrics"])
                evaluation_results["overall_metrics"]["average_credit_difference_percentage"] = avg_credit_diff_percentage
                print(f"    Average credit difference: {avg_credit_diff:.2f} ({avg_credit_diff_percentage:.1f}%)")
            
            return evaluation_results
            
        except Exception as e:
            print(f"Error evaluating exercise {exercise_id}: {e}")
            return {
                "exercise_id": exercise_id,
                "error": str(e),
            }
    
    async def run_comprehensive_test(self) -> Dict[str, Any]:
        """Run comprehensive tests on all available exercises."""
        print("Starting comprehensive playground integration test...")
        
        # Test exercises that are available
        exercises_to_test = [4, 7]  # Text exercises from playground
        
        comprehensive_results = {
            "timestamp": datetime.now().isoformat(),
            "exercises_tested": [],
            "tutor_feedback_evaluations": [],
            "summary": {},
        }
        
        # Test basic functionality
        for exercise_id in exercises_to_test:
            try:
                exercise_result = await self.run_single_exercise_test(exercise_id)
                comprehensive_results["exercises_tested"].append(exercise_result)
            except Exception as e:
                print(f"Failed to test exercise {exercise_id}: {e}")
        
        # Test tutor feedback evaluation for exercises that have it
        for exercise_id in [7]:  # Exercise 7 has tutor feedback
            try:
                evaluation_result = await self.run_tutor_feedback_evaluation(exercise_id)
                comprehensive_results["tutor_feedback_evaluations"].append(evaluation_result)
            except Exception as e:
                print(f"Failed to evaluate exercise {exercise_id}: {e}")
        
        # Generate summary
        successful_exercises = [r for r in comprehensive_results["exercises_tested"] if "error" not in r]
        successful_evaluations = [r for r in comprehensive_results["tutor_feedback_evaluations"] if "error" not in r]
        
        comprehensive_results["summary"] = {
            "total_exercises_tested": len(comprehensive_results["exercises_tested"]),
            "successful_exercises": len(successful_exercises),
            "total_evaluations": len(comprehensive_results["tutor_feedback_evaluations"]),
            "successful_evaluations": len(successful_evaluations),
        }
        
        print(f"\n{'='*60}")
        print("COMPREHENSIVE TEST SUMMARY")
        print(f"{'='*60}")
        print(f"Exercises tested: {comprehensive_results['summary']['successful_exercises']}/{comprehensive_results['summary']['total_exercises_tested']}")
        print(f"Tutor feedback evaluations: {comprehensive_results['summary']['successful_evaluations']}/{comprehensive_results['summary']['total_evaluations']}")
        
        return comprehensive_results
    
    def save_results(self, results: Dict[str, Any], output_file: str = None):
        """Save test results to a JSON file."""
        if output_file is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = f"playground_test_results_{timestamp}.json"
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, default=str)
        
        print(f"\nResults saved to: {output_file}")
        return output_file


async def main():
    """Main function to run the playground tests."""
    runner = PlaygroundTestRunner()
    
    try:
        results = await runner.run_comprehensive_test()
        output_file = runner.save_results(results)
        
        print(f"\nTest completed successfully!")
        print(f"Results saved to: {output_file}")
        
    except Exception as e:
        print(f"Test failed with error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main()) 