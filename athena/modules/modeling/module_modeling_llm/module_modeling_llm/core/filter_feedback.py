from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate

from athena import emit_meta
from module_modeling_llm.config import BasicApproachConfig
from llm_core.utils.predict_and_parse import predict_and_parse
from module_modeling_llm.models.assessment_model import AssessmentModel
from module_modeling_llm.models.exercise_model import ExerciseModel
from module_modeling_llm.prompts.filter_feedback_prompt import FilterFeedbackInputs

async def filter_feedback(
        exercise: ExerciseModel,
        original_feedback: AssessmentModel,
        config: BasicApproachConfig,
        debug: bool,
) -> AssessmentModel:
    
    print(f"\n\n\n\n\n{original_feedback.json()}\n\n\n\n\n")

    chat_prompt = ChatPromptTemplate.from_messages([
        ("system", config.generate_suggestions_prompt.filter_feedback_system_message),
        ("human", config.generate_suggestions_prompt.filter_feedback_human_message)
    ])

    prompt_inputs = FilterFeedbackInputs(
        original_feedback=original_feedback.json(),
        feedback_output_format=PydanticOutputParser(pydantic_object=AssessmentModel).get_format_instructions()
    )

    feedback_result = await predict_and_parse(
        model=config.model.get_model(), # type: ignore[attr-defined]
        chat_prompt=chat_prompt,
        prompt_input=prompt_inputs.dict(),
        pydantic_object=AssessmentModel,
        tags=[
            f"exercise-{exercise.exercise_id}-filter",
            f"submission-{exercise.submission_id}-filter",
        ]
    )

    if debug:
        emit_meta("filter_feedback", {
            "prompt": chat_prompt.format(**prompt_inputs.dict()),
            "result": feedback_result.dict() if feedback_result is not None else None
        })
    
    if feedback_result is None:
        raise ValueError("No feedback was returned by the model.")
    
    print(f"\n\n\n\n\n{feedback_result.json()}\n\n\n\n\n")
    
    return feedback_result