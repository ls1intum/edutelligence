"""Rendering of COMMAND markers from the chat history into system notes for the agent.

After Artemis carried out a command on the client, it stores a COMMAND marker in the chat history
and forwards it — as the JSON it is stored as — in every later pipeline run. The marker holds the
executed command in the same ``{type, parameters}`` shape it was sent in, so the wording the agent
reads is built here, next to the prompts, rather than in Artemis.

The notes are a record of what happened, never an instruction about what to do next. A marker says
where the student was taken earlier; it says nothing about whether they are still there, so it must
not read as if the spot were dealt with. Phrasings like "already" carry that implication and would
push the agent into silently skipping a point-out that is still the right move — repeating one is
free (the tool leaves the view untouched when the student has not moved), skipping a needed one is
not. Keep new wording purely factual and let the agent decide each turn on its own.
"""

from typing import Any

from pydantic import ValidationError

from iris.common.logging_config import get_logger
from iris.domain.status.command_dto import CommandDTO
from iris.domain.status.point_out_command_dto import PointOutParametersDTO

logger = get_logger(__name__)


def describe_command_marker(marker: dict[str, Any]) -> str:
    """Turn a COMMAND marker's JSON into the system note the agent reads.

    Dispatches on the command type; supporting a further type means adding a case. A type without a
    case — or one whose parameters do not hold up — still yields a usable sentence, so a marker can
    never break a pipeline run over its wording.

    Args:
        marker: The marker's JSON content, in the ``{type, parameters}`` shape Artemis stored.

    Returns:
        A one-sentence description of what Iris did earlier in the conversation.
    """
    try:
        command = CommandDTO.model_validate(marker)
    except ValidationError:
        logger.warning("Could not read a COMMAND marker from the chat history")
        return "Iris performed an action in the student's view earlier in this conversation."

    match command.type:
        case "pointOut":
            return _describe_point_out(command.parameters)
        case _:
            return (
                f"Iris performed a '{command.type}' action in the student's view "
                "earlier in this conversation."
            )


def _describe_point_out(parameters: dict[str, Any]) -> str:
    try:
        position = PointOutParametersDTO.model_validate(parameters).describe_position()
    except ValidationError:
        logger.warning("Could not read the parameters of a point-out marker")
        return (
            "Earlier in this conversation, Iris pointed the student to a position in "
            "the combined view."
        )
    return (
        f"Earlier in this conversation, Iris pointed the student to {position} "
        "in the combined view."
    )
