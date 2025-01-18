from typing import List
from module_text_llm.approach_config import ApproachConfig
from athena import emit_meta
from athena.text import Exercise, Submission, Feedback
from athena.logger import logger
from llm_core.utils.llm_utils import (
    get_chat_prompt_with_formatting_instructions, 
    check_prompt_length_and_omit_features_if_necessary, 
    num_tokens_from_prompt,
)
from langchain_community.chat_models import ChatOllama # type: ignore

from llm_core.utils.predict_and_parse import predict_and_parse
from module_text_llm.helpers.utils import add_sentence_numbers, get_index_range_from_line_range, format_grading_instructions
from module_text_llm.icl_rag_approach.prompt_generate_suggestions import AssessmentModel
from module_text_llm.helpers.feedback_icl.retrieve_rag_context_icl import retrieve_rag_context_icl
from module_text_llm.icl_rag_approach.agent import TutorAgent
from module_text_llm.icl_rag_approach.ollama_prompt import system_message_segment, human_message_segment, Segmentation, system_message, human_message
async def generate_suggestions(exercise: Exercise, submission: Submission, config:ApproachConfig, debug: bool, is_graded :bool) -> List[Feedback]:
    model = config.model.get_model()  # type: ignore[attr-defined]
    isOllama = isinstance(model, ChatOllama)
    if not isOllama:
        tutor = TutorAgent(config)


    formatted_rag_context = ""
    # logger.info("Formatted RAG context %s:", formatted_rag_context)
    prompt_input = {
        "max_points": exercise.max_points,
        "bonus_points": exercise.bonus_points,
        "grading_instructions": format_grading_instructions(exercise.grading_instructions, exercise.grading_criteria),
        "problem_statement": exercise.problem_statement or "No problem statement.",
        "example_solution": exercise.example_solution,
        "rag_context": formatted_rag_context,
        "submission": add_sentence_numbers(submission.text),
        "exercise_id": exercise.id,
    }

    chat_prompt = get_chat_prompt_with_formatting_instructions(
        model=model, 
        system_message=config.generate_suggestions_prompt.system_message, 
        human_message=config.generate_suggestions_prompt.human_message, 
        pydantic_object=AssessmentModel
    )

    # Check if the prompt is too long and omit features if necessary (in order of importance)
    omittable_features = ["example_solution", "problem_statement", "grading_instructions"]
    prompt_input, should_run = check_prompt_length_and_omit_features_if_necessary(
        prompt=chat_prompt,
        prompt_input= prompt_input,
        max_input_tokens=config.max_input_tokens+7000,
        omittable_features=omittable_features,
        debug=debug
    )

    # Skip if the prompt is too long
    if not should_run:
        logger.warning("Input too long. Skipping.")
        if debug:
            emit_meta("prompt", chat_prompt.format(**prompt_input))
            emit_meta("error", f"Input too long {num_tokens_from_prompt(chat_prompt, prompt_input)} > {config.max_input_tokens}")
        return []
    
    if(isOllama):
        
        segmentation_prompt = get_chat_prompt_with_formatting_instructions(
        model=model, 
        system_message=system_message_segment, 
        human_message=human_message_segment, 
        pydantic_object=Segmentation
            )
        segmentation_prompt_input = {
            "grading_instructions": format_grading_instructions(exercise.grading_instructions, exercise.grading_criteria),
            "submission": submission.text,
            "problem_statement": exercise.problem_statement or "No problem statement.",
        }
        chain = segmentation_prompt | model 
        segments = chain.invoke( segmentation_prompt_input)
        print(segments)
        for segment in segments:
            print(segment)
            print(type(segment))
            formatted_rag_context += retrieve_rag_context_icl(segment[0],exercise.id)
        prompt_input["rag_context"] = formatted_rag_context
                
        result = await predict_and_parse(
            model=model, 
            chat_prompt=chat_prompt, 
            prompt_input=prompt_input, 
            pydantic_object=AssessmentModel,
            tags=[
                f"exercise-{exercise.id}",
                f"submission-{submission.id}",
            ],
    )

        print(result)
    else :
        result = tutor.call_agent(prompt_input)

    if debug:
        emit_meta("generate_suggestions", {
            "prompt": chat_prompt.format(**prompt_input),
            "result": result.dict() if result is not None else None
        })

    if result is None:
        return []

    grading_instruction_ids = set(
        grading_instruction.id 
        for criterion in exercise.grading_criteria or [] 
        for grading_instruction in criterion.structured_grading_instructions
    )
    feedbacks = []
    for feedback in result.feedbacks:
        index_start, index_end = get_index_range_from_line_range(feedback.line_start, feedback.line_end, submission.text)
        grading_instruction_id = feedback.grading_instruction_id if feedback.grading_instruction_id in grading_instruction_ids else None
        feedbacks.append(Feedback(
            exercise_id=exercise.id,
            submission_id=submission.id,
            title=feedback.title,
            description=feedback.description,
            index_start=index_start,
            index_end=index_end,
            credits=feedback.credits,
            is_graded=is_graded,
            structured_grading_instruction_id=grading_instruction_id,
            meta={}
        ))

    return feedbacks
