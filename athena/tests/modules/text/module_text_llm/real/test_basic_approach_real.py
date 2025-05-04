import pytest
from athena.text import Exercise, Submission, Feedback
from athena.schemas.exercise_type import ExerciseType

@pytest.mark.asyncio
async def test_generate_suggestions_invalid_code(real_config):

    # Create a real exercise for testing
    exercise = Exercise(
        id=1,
        title="Python Function Exercise",
        type=ExerciseType.text,
        max_points=10,
        bonus_points=2,
        grading_instructions="",
        problem_statement="Implement a function that calculates the factorial of a given number n.",
        example_solution="def factorial(n):\n    if n == 0:\n        return 1\n    return n * factorial(n-1)",
        grading_criteria=[]
    )
    
    # Create a submission with invalid code (recursive factorial without base case)
    invalid_submission = Submission(
        id=3,
        exerciseId=exercise.id,
        text="def factorial(n):\n    return n * factorial(n)"  # Missing base case and not decrementing n
    )
    
    feedbacks = await real_config.generate_suggestions(
        exercise=exercise,
        submission=invalid_submission,
        config=real_config,
        debug=False,
        is_graded=True
    )
    for feedback in feedbacks:
        print(feedback.description)
        print("--------------------------------")
    
    assert isinstance(feedbacks, list)
    assert len(feedbacks) > 0, "Expected some feedback"
    assert any("base case" in feedback.description.lower() 
        for feedback in feedbacks), "Expected feedback about missing base case"
    assert any("n-1" in feedback.description.lower() 
        for feedback in feedbacks), "Expected feedback about decrementing n"

@pytest.mark.asyncio
async def test_generate_suggestions_string_manipulation(real_config):

    exercise = Exercise(
        id=2,
        title="String Reversal Exercise",
        type=ExerciseType.text,
        max_points=10,
        bonus_points=2,
        grading_instructions="",
        problem_statement="Implement a function that takes a string as input and returns the reversed string. Do not use any built-in reverse methods.",
        example_solution="def reverse_string(s):\n    return s[::-1]",
        grading_criteria=[]
    )
    
    invalid_submission = Submission(
        id=9,
        exerciseId=exercise.id,
        text="def reverse_string(s):\n    return s.reverse()"  # Using built-in reverse
    )
    
    feedbacks = await real_config.generate_suggestions(
        exercise=exercise,
        submission=invalid_submission,
        config=real_config,
        debug=False,
        is_graded=True
    )
    for feedback in feedbacks:
        print(feedback.description)
        print("--------------------------------")
    
    assert isinstance(feedbacks, list)
    assert len(feedbacks) > 0, "Expected feedback about using built-in reverse"
    assert any("built-in" in feedback.description.lower()  
        for feedback in feedbacks), "Expected feedback about not using built-in methods"

@pytest.mark.asyncio
async def test_generate_suggestions_list_processing(real_config):
    """Test feedback generation for a list processing exercise."""
    exercise = Exercise(
        id=3,
        title="List Deduplication Exercise",
        type=ExerciseType.text,
        max_points=10,
        bonus_points=2,
        grading_instructions="",
        problem_statement="Implement a function that takes a list as input and returns a new list with duplicates removed while maintaining the original order.",
        example_solution="def remove_duplicates(lst):\n    seen = set()\n    return [x for x in lst if not (x in seen or seen.add(x))]",
        grading_criteria=[]
    )
    
    invalid_submission = Submission(
        id=10,
        exerciseId=exercise.id,
        text="def remove_duplicates(lst):\n    return list(set(lst))"  # Doesn't preserve order
    )
    
    feedbacks = await real_config.generate_suggestions(
        exercise=exercise,
        submission=invalid_submission,
        config=real_config,
        debug=False,
        is_graded=True
    )
    for feedback in feedbacks:
        print(feedback.description)
        print("--------------------------------")
    
    assert isinstance(feedbacks, list)
    assert len(feedbacks) > 0, "Expected feedback about order preservation"
    assert any("order" in feedback.description.lower() or "preserve" in feedback.description.lower() 
        for feedback in feedbacks), "Expected feedback about preserving list order"
