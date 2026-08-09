"""Current-position content tool.

Reads out the lecture material at the position the student is looking at right now. This exists
as a tool rather than as prompt text: spelling the material out in the system prompt ends the
prompt with something that reads like a finished answer, and a weaker model then answers from it
instead of reaching for any tool at all — including the retrieval and point-out tools it would
have needed. Behind a tool the same material stays available, but only when the agent decides it
wants it.
"""

from typing import Any, Callable, Dict, List

# Key holding the rendered blocks for the student's current position.
CONTENT_BLOCKS_KEY = "content_blocks"
# Key set by the point-out tool once it moved the student away from that position.
MOVED_AWAY_KEY = "moved_away"


def create_tool_current_view_content(
    current_view_storage: Dict[str, Any],
) -> Callable[[], str]:
    """Create the current-position content tool.

    Args:
        current_view_storage: Shared mutable state describing where the student is. Holds one
            rendered block per viewed position (position description followed by its lecture
            material) under ``CONTENT_BLOCKS_KEY``. The point-out tool writes ``MOVED_AWAY_KEY``
            into it when it navigated the student elsewhere, which is why this is read on every
            call rather than captured when the tool is built.

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
        if current_view_storage.get(MOVED_AWAY_KEY):
            # The blocks are a snapshot of where the student stood when this run started. Once
            # the point-out moved them, that snapshot describes a position they have left, and
            # handing it out as what they see "right now" would have the agent answer about the
            # wrong material.
            return (
                "You already moved the student's view in this answer, so the position this tool "
                "described is no longer the one they are looking at. What you pointed them to is "
                "what they see now. Use the lecture content retrieval tool for anything else."
            )
        content_blocks: List[str] = current_view_storage.get(CONTENT_BLOCKS_KEY) or []
        if not content_blocks:
            return (
                "The material at the student's current position is not available, so there is "
                "nothing to read here. Use the lecture content retrieval tool instead."
            )
        return "\n\n".join(content_blocks)

    return read_students_current_position
