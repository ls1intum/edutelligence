from typing import List, Dict, Tuple
import math
from athena.text import Exercise, Submission, Feedback
from athena.logger import logger
from module_text_llm.approach_config import ApproachConfig
from module_text_llm.approach_controller import generate_suggestions as gen_sug

def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """Calculate cosine similarity between two vectors."""
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    norm1 = math.sqrt(sum(a * a for a in vec1))
    norm2 = math.sqrt(sum(b * b for b in vec2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot_product / (norm1 * norm2)

async def run_approach(exercise: Exercise, submission: Submission, 
                       approach_config: ApproachConfig, debug: bool, is_graded: bool) -> List[Feedback]:
    """Executes a single approach and returns suggestions, handling exceptions."""
    try:
        return await gen_sug(exercise, submission, approach_config, debug, is_graded)
    except Exception as e:
        logger.error("Error in approach %s: %s", approach_config.__class__.__name__, e)
        return []

def aggregate_feedback(feedback_list: List[Feedback]) -> Dict:
    """Aggregate credits and structured grading instruction IDs from feedback."""
    total_credits = 0
    sgi = []
    for feedback in feedback_list:
        if feedback:
            total_credits += feedback.credits
            if feedback.structured_grading_instruction_id:
                sgi.append(feedback.structured_grading_instruction_id)
    return {"credits": total_credits, "sgi": sgi}

def compute_scores(aggregated: Dict[str, Dict]) -> Dict[str, float]:
    """Computes a score for each approach based on its credits and similarity of SGIs."""
    # Compute mean credits across all approaches.
    credits_list = [info['credits'] for info in aggregated.values()]
    mean_credits = sum(credits_list) / len(credits_list) if credits_list else 0.0

    scores = {}
    for key, info in aggregated.items():
        diff = abs(info['credits'] - mean_credits)
        # Compute pairwise cosine similarity with all other approaches.
        sims = []
        for other_key, other_info in aggregated.items():
            if other_key != key:
                sims.append(cosine_similarity(info['sgi'], other_info['sgi']))
        cosine_similarity_mean = sum(sims) / len(sims) if sims else 0.0
        # Weight difference and similarity as needed.
        score = -diff * 0.8 + cosine_similarity_mean * 0.2
        scores[key] = score
    return scores

def select_best_approach(scores: Dict[str, float]) -> Tuple[str, float]:
    """Select the approach with the highest score."""
    best_key = max(scores, key=lambda k: scores[k])
    return best_key, scores[best_key]
