def get_mastery(progress: float | int, confidence: float | int) -> int:
    """
    Calculate mastery level for a competency.

    Args:
        progress (float): The user's progress.
        confidence (float): The user's confidence.

    Returns:
        int: Calculated mastery level (0-100).
    """
    return min(100, max(0, round(progress * confidence)))
