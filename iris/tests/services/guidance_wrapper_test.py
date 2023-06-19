import pytest
import guidance

from app.models.dtos import Content, ContentType, LLMModel
from app.services.guidance_wrapper import GuidanceWrapper


def test_query_success(mocker):
    mocker.patch.object(
        GuidanceWrapper,
        "_get_llm",
        return_value=guidance.llms.Mock("the output"),
    )

    handlebars = """{{#user~}}I want a response to the following query:
    {{query}}{{~/user}}{{#assistant~}}
    {{gen 'response' temperature=0.0 max_tokens=500}}{{~/assistant}}"""

    guidance_wrapper = GuidanceWrapper(
        model=LLMModel.GPT35_TURBO,
        handlebars=handlebars,
        parameters={"query": "Some query"},
    )

    result = guidance_wrapper.query()

    assert isinstance(result, Content)
    assert result.type == ContentType.TEXT
    assert result.text_content == "the output"


def test_query_missing_required_params(mocker):
    mocker.patch.object(
        GuidanceWrapper,
        "_get_llm",
        return_value=guidance.llms.Mock("the output"),
    )

    handlebars = """{{#user~}}I want a response to the following query:
    {{query}}{{~/user}}{{#assistant~}}
    {{gen 'response' temperature=0.0 max_tokens=500}}{{~/assistant}}"""

    guidance_wrapper = GuidanceWrapper(
        model=LLMModel.GPT35_TURBO,
        handlebars=handlebars,
        parameters={"somethingelse": "Something"},
    )

    with pytest.raises(KeyError, match="Command/variable 'query' not found!"):
        result = guidance_wrapper.query()

        assert isinstance(result, Content)
        assert result.type == ContentType.TEXT
        assert result.text_content == "the output"


def test_query_handlebars_not_generate_response(mocker):
    mocker.patch.object(
        GuidanceWrapper,
        "_get_llm",
        return_value=guidance.llms.Mock("the output"),
    )

    handlebars = "Not a valid handlebars"
    guidance_wrapper = GuidanceWrapper(
        model=LLMModel.GPT35_TURBO,
        handlebars=handlebars,
        parameters={"query": "Something"},
    )

    with pytest.raises(
        ValueError, match="The handlebars do not generate 'response'"
    ):
        result = guidance_wrapper.query()

        assert isinstance(result, Content)
        assert result.type == ContentType.TEXT
        assert result.text_content == "the output"
