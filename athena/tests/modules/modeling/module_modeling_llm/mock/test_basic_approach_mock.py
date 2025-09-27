import pytest
import json
from unittest.mock import patch
from athena.schemas import StructuredGradingCriterion
from athena.modeling import Submission
from module_modeling_llm.core.generate_suggestions import generate_suggestions
from module_modeling_llm.utils.get_exercise_model import get_exercise_model
from module_modeling_llm.models.assessment_model import AssessmentModel
from module_modeling_llm.models.assessment_model import FeedbackModel


@pytest.mark.asyncio
async def test_generate_suggestions_basic(mock_exercise, mock_submission, mock_config):
    """Test basic feedback generation with the adapted configuration"""
    mock_assessment_result = AssessmentModel(feedbacks=[])

    with patch(
        "module_modeling_llm.core.generate_suggestions.predict_and_parse",
        return_value=mock_assessment_result,
    ) as mock_predict:
        exercise_model = get_exercise_model(mock_exercise, mock_submission)

        await generate_suggestions(
            exercise_model=exercise_model,
            structured_grading_instructions=StructuredGradingCriterion(criteria=[]),
            config=mock_config.approach,
            debug=mock_config.debug,
        )

        mock_predict.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_suggestions_empty_submission(mock_exercise, mock_config):
    """Test feedback generation with an empty UML diagram"""
    empty_model_data = {"type": "class", "elements": {}, "relationships": {}}
    empty_submission = Submission(
        id=2,
        exercise_id=mock_exercise.id,
        model=json.dumps(empty_model_data),
        meta={},
    )

    mock_assessment_result = AssessmentModel(feedbacks=[])

    with patch(
        "module_modeling_llm.core.generate_suggestions.predict_and_parse",
        return_value=mock_assessment_result,
    ) as mock_predict:
        exercise_model = get_exercise_model(mock_exercise, empty_submission)

        feedback = await generate_suggestions(
            exercise_model=exercise_model,
            structured_grading_instructions=StructuredGradingCriterion(criteria=[]),
            config=mock_config.approach,
            debug=mock_config.debug,
        )

        assert feedback == mock_assessment_result
        assert len(feedback.feedbacks) == 0
        mock_predict.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_suggestions_complex_diagram(mock_exercise, mock_config):
    """Test feedback generation with a complex UML diagram"""
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
        exercise_id=mock_exercise.id,
        model=json.dumps(complex_model_data),
        meta={},
    )

    mock_feedbacks = [
        FeedbackModel(
            title="Class Structure",
            description="Good class structure with User and Order classes.",
            element_name="User",
            credits=3.0,
            grading_instruction_id=1,
        ),
        FeedbackModel(
            title="Relationship Types",
            description="Good use of composition relationship.",
            element_name="R1",
            credits=2.0,
            grading_instruction_id=2,
        ),
    ]
    mock_assessment_result = AssessmentModel(feedbacks=mock_feedbacks)

    with patch(
        "module_modeling_llm.core.generate_suggestions.predict_and_parse",
        return_value=mock_assessment_result,
    ) as mock_predict:
        exercise_model = get_exercise_model(mock_exercise, complex_submission)

        feedback = await generate_suggestions(
            exercise_model=exercise_model,
            structured_grading_instructions=StructuredGradingCriterion(criteria=[]),
            config=mock_config.approach,
            debug=mock_config.debug,
        )

        assert isinstance(feedback.feedbacks, list)
        assert len(feedback.feedbacks) > 0
        mock_predict.assert_awaited_once()
