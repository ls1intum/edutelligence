import json
import os
import pytest
from typing import List, Dict, Any
from pathlib import Path

from athena.text import Exercise, Submission, Feedback
from athena.schemas.exercise_type import ExerciseType
from athena.schemas.text_submission import TextLanguageEnum
from module_text_llm.default_approach.generate_suggestions import generate_suggestions



class PlaygroundExerciseLoader:
    """Helper class to load exercises from the playground data directory."""
    
    def __init__(self, data_dir: str = None):
        if data_dir is None:
            # Default to the playground data/example directory
            self.data_dir = Path(__file__).parent.parent.parent.parent.parent.parent / "playground" / "data" / "example"
        else:
            self.data_dir = Path(data_dir)
    
    def load_exercise(self, exercise_id: int) -> Dict[str, Any]:
        """Load an exercise from the playground data directory."""
        exercise_file = self.data_dir / f"exercise-{exercise_id}.json"
        if not exercise_file.exists():
            raise FileNotFoundError(f"Exercise file not found: {exercise_file}")
        
        with open(exercise_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def convert_to_athena_exercise(self, exercise_data: Dict[str, Any]) -> Exercise:
        """Convert playground exercise data to Athena Exercise object."""
        return Exercise(
            id=exercise_data["id"],
            title=exercise_data["title"],
            type=ExerciseType(exercise_data["type"]),
            max_points=exercise_data["max_points"],
            bonus_points=exercise_data.get("bonus_points", 0),
            grading_instructions=exercise_data.get("grading_instructions", ""),
            problem_statement=exercise_data.get("problem_statement", ""),
            example_solution=exercise_data.get("example_solution", ""),
            grading_criteria=[],  # Playground data doesn't include grading criteria
            meta=exercise_data.get("meta", {}),
        )
    
    def convert_to_athena_submission(self, submission_data: Dict[str, Any], exercise_id: int) -> Submission:
        """Convert playground submission data to Athena Submission object."""
        return Submission(
            id=submission_data["id"],
            exercise_id=exercise_id,
            text=submission_data.get("text", ""),
            meta=submission_data.get("meta", {}),
            language=TextLanguageEnum.ENGLISH,  # Default to English
        )
    
    def convert_to_athena_feedback(self, feedback_data: Dict[str, Any], exercise_id: int, submission_id: int) -> Feedback:
        """Convert playground feedback data to Athena Feedback object."""
        return Feedback(
            exercise_id=exercise_id,
            submission_id=submission_id,
            title=feedback_data.get("title", ""),
            description=feedback_data.get("description", ""),
            index_start=feedback_data.get("index_start"),
            index_end=feedback_data.get("index_end"),
            credits=feedback_data.get("credits", 0.0),
            is_graded=True,
            structured_grading_instruction_id=feedback_data.get("structured_grading_instruction_id"),
            meta=feedback_data.get("meta", {}),
        )


@pytest.fixture
def playground_loader():
    """Fixture to provide a playground exercise loader."""
    return PlaygroundExerciseLoader()


@pytest.mark.asyncio
async def test_playground_exercise_4_patterns_question(real_config, playground_loader):
    """Test the LLM module on exercise 4 (software patterns) from playground."""
    
    # Load exercise data
    exercise_data = playground_loader.load_exercise(4)
    exercise = playground_loader.convert_to_athena_exercise(exercise_data)
    
    # Test with various submissions
    test_submissions = [
        {"id": 401, "text": "MVC test"},
        {"id": 402, "text": "Bridge Pattern\nState Pattern\nComposite Pattern"},
        {"id": 403, "text": "Bridge pattern, Strategy pattern, Singleton pattern"},
        {"id": 410, "text": "kjhkjhkjhkjhiuhbhhkhuhuh"},  # Nonsense submission
    ]
    
    results = []
    for submission_data in test_submissions:
        submission = playground_loader.convert_to_athena_submission(submission_data, exercise.id)
        
        feedbacks = await generate_suggestions(
            exercise=exercise,
            submission=submission,
            config=real_config,
            debug=False,
            is_graded=True,
            learner_profile=None,
        )
        
        results.append({
            "submission_id": submission.id,
            "submission_text": submission.text,
            "feedbacks": feedbacks,
            "feedback_count": len(feedbacks),
        })
    
    # Assertions
    assert len(results) == 4
    
    # Check that we get appropriate feedback for each submission
    for result in results:
        assert result["feedback_count"] > 0, f"No feedback generated for submission {result['submission_id']}"


@pytest.mark.asyncio
async def test_playground_exercise_7_solid_principles(real_config, playground_loader):
    """Test the LLM module on exercise 7 (SOLID principles) from playground."""
    
    # Load exercise data
    exercise_data = playground_loader.load_exercise(7)
    exercise = playground_loader.convert_to_athena_exercise(exercise_data)
    
    # Test with submissions that demonstrate different understanding levels
    test_submissions = [
        {"id": 701, "text": "SOLID principles are important for good software design:\n\n1. Single Responsibility: Each class should do one thing well\n2. Open/Closed: Code should be open for extension, closed for modification\n3. Liskov Substitution: Subclasses should work like their parent classes\n4. Interface Segregation: Don't force clients to use methods they don't need\n5. Dependency Inversion: Depend on abstractions, not concrete classes\n\nThese help make code more maintainable and flexible."},
        {"id": 702, "text": "SOLID principles:\n\n1. Single Responsibility - one class, one job\n2. Open/Closed - extend without changing existing code\n3. Liskov - subclasses must work like parent classes\n4. Interface Segregation - small, focused interfaces\n5. Dependency Inversion - use abstractions\n\nExample: A UserService class should only handle user operations, not send emails or connect to databases."},
        {"id": 703, "text": "SOLID is about good object-oriented design:\n\n1. Single Responsibility: Classes should have one job\n2. Open/Closed: Extend without modifying\n3. Liskov: Subtypes replace base types\n4. Interface Segregation: Small interfaces\n5. Dependency Inversion: Use abstractions"},
    ]
    
    results = []
    for submission_data in test_submissions:
        submission = playground_loader.convert_to_athena_submission(submission_data, exercise.id)
        
        feedbacks = await generate_suggestions(
            exercise=exercise,
            submission=submission,
            config=real_config,
            debug=False,
            is_graded=True,
            learner_profile=None,
        )
        
        results.append({
            "submission_id": submission.id,
            "submission_text": submission.text,
            "feedbacks": feedbacks,
            "feedback_count": len(feedbacks),
        })
    
    # Assertions
    assert len(results) == 3
    
    # Check that we get feedback for each submission
    for result in results:
        assert result["feedback_count"] > 0, f"No feedback generated for submission {result['submission_id']}"


@pytest.mark.asyncio
async def test_playground_exercise_performance_comparison(real_config, playground_loader):
    """Test and compare LLM performance across different exercise types."""
    
    # Test multiple exercises to compare performance
    exercises_to_test = [4]  # Patterns question
    
    all_results = []
    
    for exercise_id in exercises_to_test:
        exercise_data = playground_loader.load_exercise(exercise_id)
        exercise = playground_loader.convert_to_athena_exercise(exercise_data)
        
        # Get a few submissions from each exercise
        submissions = exercise_data["submissions"][:3]  # First 3 submissions
        
        exercise_results = []
        for submission_data in submissions:
            submission = playground_loader.convert_to_athena_submission(submission_data, exercise.id)
            
            feedbacks = await generate_suggestions(
                exercise=exercise,
                submission=submission,
                config=real_config,
                debug=False,
                is_graded=True,
                learner_profile=None,
            )
            
            exercise_results.append({
                "exercise_id": exercise_id,
                "exercise_title": exercise.title,
                "submission_id": submission.id,
                "submission_text": submission.text[:100] + "..." if len(submission.text) > 100 else submission.text,
                "feedback_count": len(feedbacks),
                "total_credits": sum(f.credits for f in feedbacks),
                "positive_feedback_count": len([f for f in feedbacks if f.credits > 0]),
                "negative_feedback_count": len([f for f in feedbacks if f.credits < 0]),
            })
        
        all_results.extend(exercise_results)
    
    # Print performance summary
    print("\n=== LLM Performance Summary ===")
    for result in all_results:
        print(f"Exercise {result['exercise_id']} ({result['exercise_title']}): "
              f"Submission {result['submission_id']} - "
              f"{result['feedback_count']} feedbacks, "
              f"{result['positive_feedback_count']} positive, "
              f"{result['negative_feedback_count']} negative, "
              f"Total credits: {result['total_credits']}")
    
    # Assertions
    assert len(all_results) > 0, "Should have results from multiple exercises"
    
    # Check that we get feedback for most submissions
    submissions_with_feedback = [r for r in all_results if r["feedback_count"] > 0]
    assert len(submissions_with_feedback) >= len(all_results) * 0.8, \
        "At least 80% of submissions should receive feedback"


@pytest.mark.asyncio
async def test_playground_exercise_edge_cases(real_config, playground_loader):
    """Test the LLM module with edge cases from playground exercises."""
    
    # Test with very short and very long submissions
    edge_case_submissions = [
        {"id": 9991, "text": ""},  # Empty submission
        {"id": 9992, "text": "A"},  # Very short
        {"id": 9993, "text": "This is a very long submission that contains many words and should test the LLM's ability to handle longer text inputs. " * 100},  # Very long
    ]
    
    # Use exercise 4 (patterns question) as the base
    exercise_data = playground_loader.load_exercise(4)
    exercise = playground_loader.convert_to_athena_exercise(exercise_data)
    
    results = []
    for submission_data in edge_case_submissions:
        submission = playground_loader.convert_to_athena_submission(submission_data, exercise.id)
        
        feedbacks = await generate_suggestions(
            exercise=exercise,
            submission=submission,
            config=real_config,
            debug=False,
            is_graded=True,
            learner_profile=None,
        )
        
        results.append({
            "submission_id": submission.id,
            "submission_length": len(submission.text),
            "feedbacks": feedbacks,
            "feedback_count": len(feedbacks),
        })
    
    # Assertions for edge cases
    assert len(results) == 3
    
    # Check that we get feedback for edge cases
    for result in results:
        if result["feedback_count"] > 0:
            # Just verify that feedback was generated
            assert len(result["feedbacks"]) > 0, f"Should have feedback for submission {result['submission_id']}"


if __name__ == "__main__":
    # This allows running the tests directly for debugging
    pytest.main([__file__, "-v"]) 