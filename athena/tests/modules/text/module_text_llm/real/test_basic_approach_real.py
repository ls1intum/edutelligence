import pytest
from athena.text import Exercise, Submission, Feedback
from athena.schemas.exercise_type import ExerciseType

@pytest.mark.asyncio
async def test_generate_suggestions_algorithm_explanation(real_config):
    """Test feedback generation for explaining an algorithm."""
    exercise = Exercise(
        id=1,
        title="Algorithm Explanation Exercise",
        type=ExerciseType.text,
        max_points=10,
        bonus_points=2,
        grading_instructions="Explain the algorithm clearly, including its time complexity and space complexity.",
        problem_statement="Explain how the binary search algorithm works. Include its time complexity and when it should be used.",
        example_solution="Binary search is an efficient algorithm for finding an element in a sorted array. It works by repeatedly dividing the search interval in half. If the value of the search key is less than the item in the middle of the interval, narrow the interval to the lower half. Otherwise, narrow it to the upper half. The time complexity is O(log n) because we divide the search space in half each time. Space complexity is O(1) as we only use a constant amount of extra space.",
        grading_criteria=[]
    )
    
    submission = Submission(
        id=1,
        exerciseId=exercise.id,
        text="Binary search is when you look for something in a sorted list by checking the middle element. If it's not there, you look in the left or right half. It's pretty fast."
    )
    
    feedbacks = await real_config.generate_suggestions(
        exercise=exercise,
        submission=submission,
        config=real_config,
        debug=False,
        is_graded=True
    )
    
    for feedback in feedbacks:
        print(feedback.description)
        print("--------------------------------")
    
    assert isinstance(feedbacks, list)
    assert len(feedbacks) > 0, "Expected feedback about algorithm explanation"
    
    # Combine all feedback for analysis
    all_feedback = " ".join(f.description.lower() for f in feedbacks)
    
    # Technical Accuracy Checks - must include at least half of the terms
    required_complexity_terms = ["time complexity", "o(log n)", "space complexity", "o(1)"]
    found_complexity = [term for term in required_complexity_terms if term in all_feedback]
    min_required = len(required_complexity_terms) // 2
    assert len(found_complexity) >= min_required, f"Feedback must include at least {min_required} complexity terms. Found: {', '.join(found_complexity)}"
    
    required_algorithm_terms = ["sorted", "interval", "element"]
    found_algorithm = [term for term in required_algorithm_terms if term in all_feedback]
    min_required = len(required_algorithm_terms) // 2
    assert len(found_algorithm) >= min_required, f"Feedback must include at least {min_required} algorithm terms. Found: {', '.join(found_algorithm)}"

@pytest.mark.asyncio
async def test_generate_suggestions_code_documentation(real_config):
    """Test feedback generation for code documentation exercise."""
    exercise = Exercise(
        id=2,
        title="Code Documentation Exercise",
        type=ExerciseType.text,
        max_points=10,
        bonus_points=2,
        grading_instructions="Document the code's purpose, parameters, return values, and any important notes about usage.",
        problem_statement="Write documentation for a function that calculates the factorial of a number. Include its purpose, parameters, return value, and any edge cases to consider.",
        example_solution="This function calculates the factorial of a non-negative integer n. Parameters: n (int) - The number to calculate factorial for. Returns: int - The factorial of n. Note: This function will raise a ValueError if n is negative. The factorial of 0 is defined as 1.",
        grading_criteria=[]
    )
    
    submission = Submission(
        id=2,
        exerciseId=exercise.id,
        text="This function finds the factorial. It takes a number and multiplies it by all numbers below it until it reaches 1."
    )
    
    feedbacks = await real_config.generate_suggestions(
        exercise=exercise,
        submission=submission,
        config=real_config,
        debug=False,
        is_graded=True
    )
    
    for feedback in feedbacks:
        print(feedback.description)
        print("--------------------------------")
    
    assert isinstance(feedbacks, list)
    assert len(feedbacks) > 0, "Expected feedback about documentation"
    
    # Combine all feedback for analysis
    all_feedback = " ".join(f.description.lower() for f in feedbacks)
    
    # Documentation Requirements - must include at least half of the terms
    required_doc_terms = ["parameter", "return", "edge case", "negative", "0"]
    found_doc = [term for term in required_doc_terms if term in all_feedback]
    min_required = len(required_doc_terms) // 2
    assert len(found_doc) >= min_required, f"Feedback must include at least {min_required} documentation terms. Found: {', '.join(found_doc)}"

@pytest.mark.asyncio
async def test_generate_suggestions_design_pattern(real_config):
    """Test feedback generation for explaining a design pattern."""
    exercise = Exercise(
        id=3,
        title="Design Pattern Explanation Exercise",
        type=ExerciseType.text,
        max_points=10,
        bonus_points=2,
        grading_instructions="Explain the design pattern, its use cases, advantages, and disadvantages.",
        problem_statement="Explain the Singleton design pattern. Include when it should be used and its potential drawbacks.",
        example_solution="The Singleton pattern ensures a class has only one instance and provides a global point of access to it. It's useful when exactly one object is needed to coordinate actions across the system. Advantages include controlled access to the sole instance and reduced namespace pollution. Disadvantages include potential violation of the Single Responsibility Principle and difficulty in unit testing due to global state.",
        grading_criteria=[]
    )
    
    submission = Submission(
        id=3,
        exerciseId=exercise.id,
        text="Singleton is when you make sure there's only one copy of something in your program. It's good for saving memory."
    )
    
    feedbacks = await real_config.generate_suggestions(
        exercise=exercise,
        submission=submission,
        config=real_config,
        debug=False,
        is_graded=True
    )
    
    for feedback in feedbacks:
        print(feedback.description)
        print("--------------------------------")
    
    assert isinstance(feedbacks, list)
    assert len(feedbacks) > 0, "Expected feedback about design pattern explanation"
    
    # Combine all feedback for analysis
    all_feedback = " ".join(f.description.lower() for f in feedbacks)
    
    # Design Pattern Requirements - must include at least half of the terms
    required_pattern_terms = ["instance", "advantage", "drawback", "use"]
    found_pattern = [term for term in required_pattern_terms if term in all_feedback]
    min_required = len(required_pattern_terms) // 2
    assert len(found_pattern) >= min_required, f"Feedback must include at least {min_required} design pattern terms. Found: {', '.join(found_pattern)}"
