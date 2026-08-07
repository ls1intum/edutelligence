"""Current-position content tool.

Reads out the lecture material at the position the student is looking at right now. This exists
as a tool rather than as prompt text: spelling the material out in the system prompt ends the
prompt with something that reads like a finished answer, and a weaker model then answers from it
instead of reaching for any tool at all — including the retrieval and point-out tools it would
have needed. Behind a tool the same material stays available, but only when the agent decides it
wants it.
"""

from typing import Callable, List


def create_tool_current_view_content(content_blocks: List[str]) -> Callable[[], str]:
    """Create the current-position content tool.

    Args:
        content_blocks: One rendered block per viewed position (position description followed by
            its lecture material), as built for the student's current view.

    Returns:
        The tool function.
    """

    def read_students_current_position() -> str:
        """Read the lecture material at the position the student is looking at right now.

        Use this when you need to know what the student actually has in front of them — for
        instance when they ask what something on screen means, say "this slide" or "here", or
        their question only makes sense in terms of what they are currently seeing.

        This is not a search. It returns the one position the student happens to be at and
        nothing else, and that material may have nothing to do with their question. To find
        material about a topic, use the lecture content retrieval tool instead. What this tool
        returns carries no point-out id, so it cannot be passed to the point-out tool.

        Returns:
            The slide text and/or transcript at the student's current position.
        """
        if not content_blocks:
            return (
                "The material at the student's current position is not available, so there is "
                "nothing to read here. Use the lecture content retrieval tool instead."
            )
        return "\n\n".join(content_blocks)

    return read_students_current_position
