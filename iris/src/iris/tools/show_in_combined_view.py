"""Tool that lets Iris point the student to a position in the combined view."""

from typing import Any, Callable, Dict, Optional

from ..web.status.status_update import StatusCallback


def create_tool_show_in_combined_view(
    lecture_unit_id: int,
    callback: StatusCallback,
    point_out_storage: Dict[str, Any],
) -> Callable[[Optional[int], Optional[float], str], str]:
    """
    Create a tool that points the student to a slide page and/or video timestamp
    in the lecture combined view they are currently looking at.

    The tool only records the requested navigation target (validated and stored
    in ``point_out_storage``); the actual navigation happens on the Artemis client
    when the final response is delivered. It is only offered to the agent when the
    student is currently in the combined view (see ``provide_show_in_combined_view``).

    Args:
        lecture_unit_id: The lecture unit the student is currently viewing.
        callback: Callback for status updates.
        point_out_storage: Shared storage the recorded action is written into.

    Returns:
        The tool function.
    """

    def show_in_combined_view(
        page: Optional[int] = None,
        timestamp: Optional[float] = None,
        reason: str = "",
    ) -> str:
        """
        Show the student a specific slide page and/or video timestamp in the lecture
        combined view they are currently looking at. The slides jump to the page and/or
        the video seeks to the timestamp on their screen, so you can then refer to it
        naturally in your answer (e.g. "as you can see on the slide I just opened ...").

        Use this ONLY when pointing to a concrete page or moment directly helps answer
        the student's question, and only for content you actually know exists (e.g. a
        page/timestamp returned by the lecture retrieval tool or the slide you were told
        the student is currently viewing). Call it at most once.

        Args:
            page: 1-based slide page number to display (optional).
            timestamp: Video position in seconds to seek to (optional).
            reason: Short human-readable label of what is being shown
                (e.g. "Definition of binary search"). Shown to the student on the
                clickable marker in the chat.

        Returns:
            A short confirmation of what was shown.
        """
        if (page is None or page < 1) and (timestamp is None or timestamp < 0):
            return (
                "No valid page or timestamp was provided, so nothing was shown to "
                "the student. Provide a page (>= 1) and/or a timestamp (>= 0)."
            )

        normalized_page = page if page is not None and page >= 1 else None
        normalized_timestamp = (
            timestamp if timestamp is not None and timestamp >= 0 else None
        )

        callback.in_progress("Showing the relevant lecture content ...")

        point_out_storage["action"] = {
            "lecture_unit_id": lecture_unit_id,
            "page": normalized_page,
            "timestamp": normalized_timestamp,
            "reason": reason or None,
        }

        shown = []
        if normalized_page is not None:
            shown.append(f"page {normalized_page} of the slides")
        if normalized_timestamp is not None:
            shown.append(f"the video at {normalized_timestamp:.0f} seconds")
        shown_text = " and ".join(shown)
        return f"Successfully showed the student {shown_text}."

    return show_in_combined_view
