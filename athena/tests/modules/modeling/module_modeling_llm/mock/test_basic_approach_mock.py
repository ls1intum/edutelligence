import pytest
import json
from athena.modeling import Submission
from module_modeling_llm.utils.get_exercise_model import get_exercise_model
from mod.core.generate_suggestions import generate_suggestions
from tests.modules.modeling.module_modeling_llm.mock.utils.mock_llm import MockLanguageModel, MockAssessmentModel, MockFeedbackModel
from tests.modules.modeling.module_modeling_llm.mock.utils.mock_config import MockApproachConfig, MockModelConfig
from tests.modules.modeling.module_modeling_llm.mock.conftest import MockPrompt
from unittest.mock import patch

@pytest.mark.asyncio
async def test_generate_suggestions_basic(mock_exercise, mock_submission, mock_config, mock_grading_criterion):
    """Test basic feedback generation with a simple UML diagram."""
    mock_model = MockLanguageModel(return_value=MockAssessmentModel(feedbacks=[
        MockFeedbackModel(
            title="Test Feedback",
            description="Test description",
            line_start=1,
            line_end=2,
            credits=5.0,
            exercise_id=mock_exercise.id,
            submission_id=mock_submission.id
        )
    ]))
    mock_config.model.get_model = lambda: mock_model
    mock_config.generate_suggestions_prompt = MockPrompt(
        graded_feedback_system_message="Test system message",
        graded_feedback_human_message="Test human message"
    )

    with patch('module_modeling_llm.core.generate_suggestions.predict_and_parse', return_value=mock_model.return_value):
        exercise_model = get_exercise_model(mock_exercise, mock_submission)
        feedback = await generate_suggestions(
            exercise_model, mock_grading_criterion, mock_config, debug=False
        )

        assert isinstance(feedback.feedbacks, list)
        assert len(feedback.feedbacks) > 0
        assert all(f.exercise_id == mock_exercise.id for f in feedback.feedbacks)
        assert all(f.submission_id == mock_submission.id for f in feedback.feedbacks)

@pytest.mark.asyncio
async def test_generate_suggestions_empty_submission(mock_exercise, mock_config, mock_grading_criterion):
    """Test feedback generation with an empty UML diagram."""
    empty_model_data = {
        "type": "class",
        "elements": {},
        "relationships": {}
    }
    empty_submission = Submission(
        id=2,
        exerciseId=mock_exercise.id,
        model=json.dumps(empty_model_data)
    )
    mock_model = MockLanguageModel(return_value=MockAssessmentModel(feedbacks=[]))
    mock_config.model.get_model = lambda: mock_model
    mock_config.generate_suggestions_prompt = MockPrompt(
        graded_feedback_system_message="Test system message",
        graded_feedback_human_message="Test human message"
    )

    exercise_model = get_exercise_model(mock_exercise, empty_submission)
    feedback = await generate_suggestions(
        exercise_model, mock_grading_criterion, mock_config, debug=False
    )

    assert isinstance(feedback.feedbacks, list)
    assert len(feedback.feedbacks) == 0

@pytest.mark.asyncio
async def test_generate_suggestions_complex_diagram(mock_exercise, mock_config, mock_grading_criterion):
    """Test feedback generation with a complex UML diagram."""
    complex_model_data = {
        "type": "class",
        "elements": {
            "1": {
                "id": "1",
                "type": "class",
                "name": "User",
                "attributes": ["2", "3", "4"]
            },
            "2": {
                "id": "2",
                "type": "attribute",
                "name": "name"
            },
            "3": {
                "id": "3",
                "type": "attribute",
                "name": "email"
            },
            "4": {
                "id": "4",
                "type": "attribute",
                "name": "password"
            },
            "5": {
                "id": "5",
                "type": "class",
                "name": "Order",
                "attributes": ["6", "7", "8"]
            },
            "6": {
                "id": "6",
                "type": "attribute",
                "name": "orderId"
            },
            "7": {
                "id": "7",
                "type": "attribute",
                "name": "date"
            },
            "8": {
                "id": "8",
                "type": "attribute",
                "name": "status"
            },
            "9": {
                "id": "9",
                "type": "class",
                "name": "Product",
                "attributes": ["10", "11", "12"]
            },
            "10": {
                "id": "10",
                "type": "attribute",
                "name": "productId"
            },
            "11": {
                "id": "11",
                "type": "attribute",
                "name": "name"
            },
            "12": {
                "id": "12",
                "type": "attribute",
                "name": "price"
            },
            "13": {
                "id": "13",
                "type": "class",
                "name": "Cart",
                "attributes": ["14", "15"]
            },
            "14": {
                "id": "14",
                "type": "attribute",
                "name": "cartId"
            },
            "15": {
                "id": "15",
                "type": "attribute",
                "name": "total"
            },
            "16": {
                "id": "16",
                "type": "class",
                "name": "Address",
                "attributes": ["17", "18", "19"]
            },
            "17": {
                "id": "17",
                "type": "attribute",
                "name": "street"
            },
            "18": {
                "id": "18",
                "type": "attribute",
                "name": "city"
            },
            "19": {
                "id": "19",
                "type": "attribute",
                "name": "zip"
            }
        },
        "relationships": {
            "1": {
                "id": "1",
                "type": "composition",
                "source": {"element": "1"},
                "target": {"element": "5"}
            },
            "2": {
                "id": "2",
                "type": "association",
                "source": {"element": "5"},
                "target": {"element": "9"}
            },
            "3": {
                "id": "3",
                "type": "composition",
                "source": {"element": "13"},
                "target": {"element": "9"}
            },
            "4": {
                "id": "4",
                "type": "aggregation",
                "source": {"element": "1"},
                "target": {"element": "16"}
            }
        }
    }
    complex_submission = Submission(
        id=3,
        exerciseId=mock_exercise.id,
        model=json.dumps(complex_model_data)
    )
    mock_model = MockLanguageModel(return_value=MockAssessmentModel(feedbacks=[
        MockFeedbackModel(
            title="Class Structure and Relationships",
            description="The class structure is well-organized with clear separation of concerns. User, Order, Product, Cart, and Address classes are properly defined with appropriate attributes.",
            line_start=1,
            line_end=19,
            credits=3.0,
            exercise_id=mock_exercise.id,
            submission_id=complex_submission.id
        ),
        MockFeedbackModel(
            title="Relationship Types",
            description="Good use of different relationship types: composition between User and Order, association between Order and Product, composition between Cart and Product, and aggregation between User and Address.",
            line_start=1,  
            line_end=4,    
            credits=2.0,
            exercise_id=mock_exercise.id,
            submission_id=complex_submission.id
        ),
        MockFeedbackModel(
            title="Attribute Completeness",
            description="All classes have appropriate attributes. User has name, email, and password; Order has orderId, date, and status; Product has productId, name, and price; Cart has cartId and total; Address has street, city, and zip.",
            line_start=2,  
            line_end=19,   
            credits=2.0,
            exercise_id=mock_exercise.id,
            submission_id=complex_submission.id
        )
    ]))
    mock_config.model.get_model = lambda: mock_model
    mock_config.generate_suggestions_prompt = MockPrompt(
        graded_feedback_system_message="Test system message",
        graded_feedback_human_message="Test human message"
    )

    with patch('module_modeling_llm.core.generate_suggestions.predict_and_parse', return_value=mock_model.return_value):
        exercise_model = get_exercise_model(mock_exercise, complex_submission)
        feedback = await generate_suggestions(
            exercise_model, mock_grading_criterion, mock_config, debug=False
        )

        assert isinstance(feedback.feedbacks, list)
        assert len(feedback.feedbacks) > 0
        assert all(f.exercise_id == mock_exercise.id for f in feedback.feedbacks)
        assert all(f.submission_id == complex_submission.id for f in feedback.feedbacks) 