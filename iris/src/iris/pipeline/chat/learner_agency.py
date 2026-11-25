"""Classify the current request and plan one turn of the learner's choice workflow."""

import json

from iris.common.logging_config import get_logger
from iris.common.pyris_message import IrisMessageRole, PyrisMessage
from iris.domain.chat.learner_agency_dto import LearnerAgencyTurn, SolutionOffer
from iris.domain.data.json_message_content_dto import JsonMessageContentDTO
from iris.domain.data.text_message_content_dto import TextMessageContentDTO
from iris.learner_agency_settings import LearnerAgencySettings
from iris.llm.completion_arguments import CompletionArguments
from iris.llm.request_handler.llm_request_handler import LlmRequestHandler
from iris.pipeline.chat.iris_chat_mode import IrisChatMode

logger = get_logger(__name__)


def _text(message: PyrisMessage) -> str:
    return "\n".join(
        content.text_content
        for content in message.contents
        if isinstance(content, TextMessageContentDTO)
    )


def _payload(message: PyrisMessage, kind: str) -> dict | None:
    for content in message.contents:
        if isinstance(content, JsonMessageContentDTO):
            payload = content.json_content
            if isinstance(payload, dict) and payload.get("type") == kind:
                return payload
    return None


def plan_turn(
    dto, config: LearnerAgencySettings, *, event: str | None
) -> LearnerAgencyTurn:
    """Run before history windowing/compaction. Explicit server-validated choices take priority."""
    turn = LearnerAgencyTurn()
    if getattr(dto, "chat_mode", None) not in (
        IrisChatMode.EXERCISE,
        IrisChatMode.TEXT_EXERCISE,
    ):
        return turn
    history = [
        m
        for m in getattr(dto, "chat_history", [])
        if m.sender != IrisMessageRole.SUMMARY
    ]
    if event or not history or history[-1].sender != IrisMessageRole.USER:
        return turn
    latest = history[-1]
    choice = _payload(latest, "solution-choice")
    if choice is not None:
        # Artemis validates/consumes the offer under a database lock. Check its binding here too:
        # arbitrary JSON elsewhere in history must never grant solution permission.
        if len(history) < 2 or history[-2].sender != IrisMessageRole.ASSISTANT:
            return turn
        previous = history[-2]
        offer = _payload(previous, "solution-offer")
        expected = context_offer(dto)
        if (
            offer is not None
            and previous.id is not None
            and choice.get("offerMessageId") == previous.id
            and offer.get("chatMode") == expected.chat_mode
            and offer.get("entityId") == expected.entity_id
        ):
            if choice.get("choice") == "SHOW_SOLUTION":
                turn.mode = "solution"
            elif choice.get("choice") == "TRY_MYSELF":
                turn.mode = "hint"
        return turn
    execution_settings = getattr(dto, "settings", None)
    local = execution_settings is not None and execution_settings.is_local()
    model_id = config.classifier_model_local if local else config.classifier_model
    if not model_id or not _text(latest).strip():
        return turn
    # Send the entire stored dialogue, not the agent's compacted/sliding history.
    conversation = [
        {"role": m.sender.value, "text": _text(m), "isTarget": m is latest}
        for m in history
        if m.sender in (IrisMessageRole.USER, IrisMessageRole.ASSISTANT)
    ]
    try:
        handler = LlmRequestHandler(model_id=model_id)
        if handler.supports_decisions():
            result = handler.decide(
                json.dumps(conversation, ensure_ascii=False), config.classifier_prompt
            )
            turn.tokens.append(result.token_usage)
            if result.probability > config.classifier_threshold:
                turn.mode = "offer"
            return turn
        response = handler.chat(
            [
                PyrisMessage(
                    sender=IrisMessageRole.SYSTEM,
                    contents=[
                        TextMessageContentDTO(
                            textContent=config.classifier_prompt
                            + "\nReply with exactly YES or NO, without explanation."
                        )
                    ],
                ),
                PyrisMessage(
                    sender=IrisMessageRole.USER,
                    contents=[
                        TextMessageContentDTO(
                            textContent=json.dumps(conversation, ensure_ascii=False)
                        )
                    ],
                ),
            ],
            CompletionArguments(
                temperature=0,
                max_tokens=config.classifier_max_tokens,
                reasoning_effort="low",
            ),
            tools=None,
        )
        turn.tokens.append(response.token_usage)
        decision = _text(response).strip().upper()
        if decision == "YES":
            turn.mode = "offer"
        elif decision != "NO":
            logger.warning(
                "Solution classifier returned an invalid decision; continuing with tutoring"
            )
    except Exception as error:
        # Keep ordinary tutoring available if the classifier is down.
        usage = getattr(error, "token_usage", None)
        if usage is not None:
            turn.tokens.append(usage)
        logger.warning(
            "Solution classification failed; continuing with tutoring", exc_info=True
        )
    return turn


def context_offer(dto) -> SolutionOffer:
    """Bind both buttons to the active exercise."""
    entity = dto.programming_exercise or dto.text_exercise
    if entity is None:
        raise ValueError("A solution offer requires an exercise context")
    return SolutionOffer(chatMode=dto.chat_mode.value, entityId=entity.id)


def localized(config: LearnerAgencySettings, name: str, dto) -> str:
    language = "de" if dto.user.lang_key == "de" else "en"
    return getattr(config, f"{name}_{language}")


def reference_solution_for_turn(dto) -> str | None:
    """Expose instructor material only to the explicitly authorized solution turn."""
    if get_turn(dto).mode != "solution":
        return None
    if dto.chat_mode == IrisChatMode.EXERCISE:
        exercise = dto.programming_exercise
        files = getattr(exercise, "solution_repository", {}) or {}
        nonempty = {path: content for path, content in files.items() if content.strip()}
        return (
            json.dumps(nonempty, ensure_ascii=False, sort_keys=True)
            if nonempty
            else None
        )
    if dto.chat_mode == IrisChatMode.TEXT_EXERCISE:
        text = getattr(dto.text_exercise, "example_solution", None)
        return text if text and text.strip() else None
    return None


def get_turn(dto) -> LearnerAgencyTurn:
    """Allow pipeline fixtures and older callers without turn metadata."""
    return getattr(dto, "_learner_agency_turn", LearnerAgencyTurn())


def finalize_solution(text: str, dto, config: LearnerAgencySettings) -> str:
    """Append reflection to a delivered solution answer without model-generated flags."""
    if get_turn(dto).mode != "solution":
        return text
    # Strip the old marker too, in case an in-flight run still used the earlier prompt.
    text = text.replace("<iris-solution-complete/>", "").rstrip()
    if not text.strip():
        return text
    reflection = localized(config, "reflection", dto).strip()
    if reflection and not text.endswith(reflection):
        text += "\n\n" + reflection
    return text
