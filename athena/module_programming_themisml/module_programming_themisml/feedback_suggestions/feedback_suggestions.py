import asyncio
import concurrent
from multiprocessing import get_context
from typing import Dict, List

from athena.logger import logger
from athena.models import DBProgrammingFeedback
from athena.schemas import ProgrammingFeedback

from module_programming_themisml.extract_methods.method_node import MethodNode
from .code_similarity_computer import CodeSimilarityComputer

SIMILARITY_SCORE_THRESHOLD = 0.75
ASYNC_PROCESSING = True  # faster, but worse for debugging


def get_feedback_suggestions_for_method(
        feedbacks: List[DBProgrammingFeedback],
        filepath: str,
        method: MethodNode,
        include_code: bool = False
) -> List[ProgrammingFeedback]:
    """
    Get feedback suggestions from comparisons between a function block of a given submission
    and multiple feedback rows
    """
    considered_feedbacks = []
    sim_computer = CodeSimilarityComputer()
    for feedback in feedbacks:
        if feedback.file_path == filepath and feedback.meta.get("method_name") == method.name:
            considered_feedbacks.append(feedback)
            sim_computer.add_comparison(method.source_code, feedback.get_referenced_code())

    sim_computer.compute_similarity_scores()

    suggested = []
    for feedback in considered_feedbacks:
        feedback_code = feedback.get_referenced_code()
        similarity = sim_computer.get_similarity_score(method.source_code, feedback_code)
        if similarity.f1 >= SIMILARITY_SCORE_THRESHOLD:
            logger.info("Found similar code with similarity score %d: %s", similarity, feedback)
            original_code = feedback_code
            feedback_to_give = feedback.to_schema()
            if include_code:
                feedback_to_give.meta["code"] = method.source_code
            feedback_to_give.line_start = method.line_start
            feedback_to_give.line_end = method.line_end
            feedback_to_give.meta = {
                **feedback_to_give.meta,
                "precision_score": similarity.precision,
                "recall_score": similarity.recall,
                "similarity_score": similarity.f1,
                "similarity_score_f3": similarity.f3,
            }
            if include_code:
                feedback_to_give.meta["originally_on_code"] = original_code
            suggested.append(feedback_to_give)
    return sorted(suggested, key=lambda f: f.meta["similarity_score"], reverse=True)


async def get_feedback_suggestions(
        function_blocks: Dict[str, List[MethodNode]],
        feedbacks: List[DBProgrammingFeedback],
        include_code: bool = False
) -> List[ProgrammingFeedback]:
    """
    Get feedback suggestions from comparisons between function blocks of a given submission
    and multiple feedback rows.
    This is quicker than calling get_feedback_suggestions_for_method for each method
    because it uses multiple processes to do the comparisons in parallel.
    """
    if ASYNC_PROCESSING:
        loop = asyncio.get_event_loop()
        # Doing it like this for compatibility with FastAPI / Uvicorn, see https://github.com/tiangolo/fastapi/issues/1487#issuecomment-657290725
        with concurrent.futures.ProcessPoolExecutor(mp_context=get_context("spawn")) as pool:  # type: ignore
            results = await asyncio.gather(*[
                loop.run_in_executor(pool, get_feedback_suggestions_for_method,
                                    feedbacks, filepath, method, include_code)
                for filepath, methods in function_blocks.items()
                for method in methods
            ])
    else:
        results = []
        for filepath, methods in function_blocks.items():
            for method in methods:
                results.append(get_feedback_suggestions_for_method(feedbacks, filepath, method, include_code))
    return [result for result_list in results for result in result_list]
