"""Tool that lets Iris point the student to a position in the combined view."""

from typing import Callable, Optional

from ..domain.status.point_out_command_dto import PointOutCommandDTO
from ..web.status.status_update import StatusCallback


def create_tool_show_in_combined_view(
    lecture_unit_id: int,
    callback: StatusCallback,
) -> Callable[[Optional[int], Optional[float]], str]:
    """
    Create a tool that points the student to a slide page and/or video timestamp
    in the lecture combined view they are currently looking at.

    The tool asks Artemis to carry out the navigation immediately and waits for the result: if the
    student is still in the combined view it is navigated and a marker is left in the chat, otherwise
    nothing is shown. It is only offered to the agent when the student is currently in the combined
    view (see ``provide_show_in_combined_view``).

    Args:
        lecture_unit_id: The lecture unit the student is currently viewing.
        callback: Callback for status updates and command execution.

    Returns:
        The tool function.
    """

    def show_in_combined_view(
        page: Optional[int] = None,
        timestamp: Optional[float] = None,
    ) -> str:
        """
        Show the student a specific slide page and/or video timestamp in the lecture
        combined view they are currently looking at. The slides jump to the page and/or
        the video seeks to the timestamp on their screen, so you can then refer to it
        naturally in your answer (e.g. "as you can see on the slide I just opened ...").

        For content-related lecture questions, you should usually use this when you know
        the most relevant slide page or video moment. There is no need for it on
        non-content messages (greetings, small talk, thanks) or when you do not know a
        concrete page/timestamp. Prefer the single most relevant spot and use it at most
        once per answer.

        Only point to content you actually know exists (e.g. a page/timestamp from the
        lecture retrieval tool or the slide/timestamp the student is currently viewing).
        Only mention having opened or shown something if the tool result explicitly
        confirms success. If there is no such success confirmation, just continue
        with a normal answer and act as if no point-out happened.

        Args:
            page: 1-based slide page number to display (optional).
            timestamp: Video position in seconds to seek to (optional).

        Returns:
            A short confirmation of what was shown.
        """
        if (page is None or page < 1) and (timestamp is None or timestamp < 0):
            return ""

        normalized_page = page if page is not None and page >= 1 else None
        normalized_timestamp = (
            timestamp if timestamp is not None and timestamp >= 0 else None
        )

        callback.in_progress("Showing the relevant lecture content ...")

        result = callback.execute_command(
            PointOutCommandDTO(
                lecture_unit_id=lecture_unit_id,
                page=normalized_page,
                timestamp=normalized_timestamp,
            )
        )

        if not result.applied:
            return ""

        shown = []
        if normalized_page is not None:
            shown.append(f"page {normalized_page} of the slides")
        if normalized_timestamp is not None:
            shown.append(f"the video at {normalized_timestamp:.0f} seconds")
        shown_text = " and ".join(shown)
        return f"Successfully showed the student {shown_text}."

    return show_in_combined_view
