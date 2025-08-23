from langchain_core.prompts import ChatPromptTemplate

from athena import emit_meta
from module_modeling_llm.config import BasicApproachConfig
from llm_core.core.predict_and_parse import predict_and_parse
from module_modeling_llm.models.assessment_model import AssessmentModel
from module_modeling_llm.models.exercise_model import ExerciseModel
from module_modeling_llm.prompts.filter_feedback_prompt import FilterFeedbackInputs

async def filter_feedback(
        exercise: ExerciseModel,
        original_feedback: AssessmentModel,
        config: BasicApproachConfig,
        debug: bool,
) -> AssessmentModel:
    
    print(f"\n\n\n\n\n{original_feedback.model_dump_json()}\n\n\n\n\n")

    chat_prompt = ChatPromptTemplate.from_messages([
        ("system", config.generate_suggestions_prompt.filter_feedback_system_message),
        ("human", config.generate_suggestions_prompt.filter_feedback_human_message)
    ])

    prompt_inputs = FilterFeedbackInputs(
        original_feedback=original_feedback.model_dump_json(),
    )

    feedback_result = await predict_and_parse(
        model=config.filter_feedback,
        chat_prompt=chat_prompt,
        prompt_input=prompt_inputs.model_dump(),
        pydantic_object=AssessmentModel,
        tags=[
            f"exercise-{exercise.exercise_id}-filter",
            f"submission-{exercise.submission_id}-filter",
        ]
    )

    if debug:
        emit_meta("filter_feedback", {
            "prompt": chat_prompt.format(**prompt_inputs.model_dump()),
            "result": feedback_result.model_dump() if feedback_result is not None else None
        })
    
    if feedback_result is None:
        raise ValueError("No feedback was returned by the model.")
    
    print(f"\n\n\n\n\n{feedback_result.model_dump_json()}\n\n\n\n\n")
    
    return feedback_result
