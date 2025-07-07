import pytest
import json
from athena.modeling import Submission
from module_modeling_llm.core.generate_suggestions import generate_suggestions
from module_modeling_llm.models.assessment_model import AssessmentModel, FeedbackModel
from module_modeling_llm.utils.get_exercise_model import get_exercise_model
from modules.modeling.module_modeling_llm.mock.conftest import TestData, TestEnvironment


@pytest.mark.asyncio
async def test_generate_suggestions_basic(
    test_data: TestData, test_env: TestEnvironment
):
    """
    Test basic feedback generation with a simple UML diagram.
    This test uses the new dependency injection approach, without any patching.
    """
    # 1. Arrange: Define the response our fake LLM will return and queue it.
    expected_feedback = AssessmentModel(
        feedbacks=[
            FeedbackModel(
                # FIX: Corrected syntax from ':' to '=' and added the argument.
                element_name="User",
                title="Test Feedback",
                description="Test description",
                credits=5.0,
                grading_instruction_id=1,
            )
        ]
    )
    test_env.fake_model.add_response(expected_feedback)

    # Convert exercise/submission to the internal ExerciseModel
    exercise_model = get_exercise_model(test_data.exercise, test_data.submission)

    # 2. Act: Call the function we want to test. No patches are needed.
    actual_feedback = await generate_suggestions(
        exercise_model=exercise_model,
        structured_grading_instructions=test_data.structured_grading_instructions,
        config=test_env.config.approach,
        debug=test_env.config.debug,
    )

    # 3. Assert: Check that the output matches the expected response and the LLM was called.
    assert actual_feedback == expected_feedback
    assert len(test_env.fake_model.requests) == 1


@pytest.mark.asyncio
async def test_generate_suggestions_empty_submission(
    test_data: TestData, test_env: TestEnvironment
):
    """Test feedback generation with an empty UML diagram."""
    # 1. Arrange
    # Create an empty submission for this specific test case
    empty_model_data = {"type": "class", "elements": {}, "relationships": {}}
    empty_submission = Submission(
        id=2,
        exercise_id=test_data.exercise.id,
        model=json.dumps(empty_model_data),
        meta={},
    )
    exercise_model = get_exercise_model(test_data.exercise, empty_submission)

    expected_feedback = AssessmentModel(feedbacks=[])
    test_env.fake_model.add_response(expected_feedback)

    actual_feedback = await generate_suggestions(
        exercise_model=exercise_model,
        structured_grading_instructions=test_data.structured_grading_instructions,
        config=test_env.config.approach,
        debug=test_env.config.debug,
    )

    assert actual_feedback == expected_feedback
    assert len(actual_feedback.feedbacks) == 0
    assert len(test_env.fake_model.requests) == 1


@pytest.mark.asyncio
async def test_generate_suggestions_complex_diagram(
    test_data: TestData, test_env: TestEnvironment
):
    """Test feedback generation with a complex UML diagram, using the new pattern."""
    # 1. Arrange
    # Define the truly complex submission data, as it was in the original test.
    complex_model_data = {
        "type": "class",
        "elements": {
            "1": {
                "id": "1",
                "type": "class",
                "name": "User",
                "attributes": ["2", "3", "4"],
            },
            "2": {"id": "2", "type": "attribute", "name": "name"},
            "3": {"id": "3", "type": "attribute", "name": "email"},
            "4": {"id": "4", "type": "attribute", "name": "password"},
            "5": {
                "id": "5",
                "type": "class",
                "name": "Order",
                "attributes": ["6", "7", "8"],
            },
            "6": {"id": "6", "type": "attribute", "name": "orderId"},
            "7": {"id": "7", "type": "attribute", "name": "date"},
            "8": {"id": "8", "type": "attribute", "name": "status"},
            "9": {
                "id": "9",
                "type": "class",
                "name": "Product",
                "attributes": ["10", "11", "12"],
            },
            "10": {"id": "10", "type": "attribute", "name": "productId"},
            "11": {"id": "11", "type": "attribute", "name": "name"},
            "12": {"id": "12", "type": "attribute", "name": "price"},
            "13": {
                "id": "13",
                "type": "class",
                "name": "Cart",
                "attributes": ["14", "15"],
            },
            "14": {"id": "14", "type": "attribute", "name": "cartId"},
            "15": {"id": "15", "type": "attribute", "name": "total"},
            "16": {
                "id": "16",
                "type": "class",
                "name": "Address",
                "attributes": ["17", "18", "19"],
            },
            "17": {"id": "17", "type": "attribute", "name": "street"},
            "18": {"id": "18", "type": "attribute", "name": "city"},
            "19": {"id": "19", "type": "attribute", "name": "zip"},
        },
        "relationships": {
            "1": {
                "id": "1",
                "type": "composition",
                "source": {"element": "1"},
                "target": {"element": "5"},
            },
            "2": {
                "id": "2",
                "type": "association",
                "source": {"element": "5"},
                "target": {"element": "9"},
            },
            "3": {
                "id": "3",
                "type": "composition",
                "source": {"element": "13"},
                "target": {"element": "9"},
            },
            "4": {
                "id": "4",
                "type": "aggregation",
                "source": {"element": "1"},
                "target": {"element": "16"},
            },
        },
    }
    complex_submission = Submission(
        id=3,
        exercise_id=test_data.exercise.id,
        model=json.dumps(complex_model_data),
        meta={},
    )
    exercise_model = get_exercise_model(test_data.exercise, complex_submission)

    # Define and queue the detailed response we expect from the LLM for this complex case.
    # FIX: Added the 'element_name' argument to each FeedbackModel instance.
    expected_feedback = AssessmentModel(
        feedbacks=[
            FeedbackModel(
                element_name="User",
                title="Class Structure and Relationships",
                description="The class structure is well-organized with clear separation of concerns. User, Order, Product, Cart, and Address classes are properly defined with appropriate attributes.",
                credits=3.0,
                grading_instruction_id=1,
            ),
            FeedbackModel(
                element_name="R2",
                title="Relationship Types",
                description="Good use of different relationship types: composition between User and Order, association between Order and Product, composition between Cart and Product, and aggregation between User and Address.",
                credits=2.0,
                grading_instruction_id=2,
            ),
            FeedbackModel(
                element_name=None,
                title="Attribute Completeness",
                description="All classes have appropriate attributes. User has name, email, and password; Order has orderId, date, and status; Product has productId, name, and price; Cart has cartId and total; Address has street, city, and zip.",
                credits=2.0,
                grading_instruction_id=3,
            ),
        ]
    )
    test_env.fake_model.add_response(expected_feedback)

    # 2. Act
    actual_feedback = await generate_suggestions(
        exercise_model=exercise_model,
        structured_grading_instructions=test_data.structured_grading_instructions,
        config=test_env.config.approach,
        debug=test_env.config.debug,
    )

    # 3. Assert
    assert actual_feedback == expected_feedback
    assert len(actual_feedback.feedbacks) == 3
    assert len(test_env.fake_model.requests) == 1
