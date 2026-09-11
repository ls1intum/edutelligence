from iris.common.pipeline_enum import PipelineEnum


def test_ask_user_pipeline_enum_values_are_present():
    assert PipelineEnum.IRIS_ASK_USER == "IRIS_ASK_USER"
    assert PipelineEnum.IRIS_ASSESS_USER_ANSWER == "IRIS_ASSESS_USER_ANSWER"


def test_ask_user_pipeline_enum_members_are_unique():
    values = [member.value for member in PipelineEnum]
    assert len(values) == len(set(values))


def test_ask_user_pipeline_enum_members_are_strings():
    # PipelineEnum mixes in str so members can be used directly as JSON values
    assert isinstance(PipelineEnum.IRIS_ASK_USER, str)
    assert isinstance(PipelineEnum.IRIS_ASSESS_USER_ANSWER, str)
