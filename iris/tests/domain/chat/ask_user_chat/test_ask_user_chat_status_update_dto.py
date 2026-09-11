from iris.domain.chat.ask_user_chat.ask_user_chat_status_update_dto import (
    AskUserChatStatusUpdateDTO,
)
from iris.domain.data.verdict_dto import VerdictDTO
from iris.domain.status.run_state_dto import RunStateEnum


def test_result_verdict_and_event_default_to_none():
    status = AskUserChatStatusUpdateDTO(runState=RunStateEnum.RUNNING)

    assert status.result is None
    assert status.verdict is None
    assert status.event is None


def test_accepts_result_verdict_and_event():
    verdict = VerdictDTO(verdict="UNSUSPICIOUS", reasoning="Solid understanding.")

    status = AskUserChatStatusUpdateDTO(
        runState=RunStateEnum.RUNNING,
        result="Here is your next question.",
        verdict=verdict,
        event="NEXT_QUESTION",
    )

    assert status.result == "Here is your next question."
    assert status.verdict == verdict
    assert status.event == "NEXT_QUESTION"


def test_serializes_with_wire_format_aliases():
    status = AskUserChatStatusUpdateDTO(
        runState=RunStateEnum.RUNNING, event="FIRST_QUESTION"
    )

    dumped = status.model_dump(by_alias=True)

    assert dumped["runState"] == "RUNNING"
    assert dumped["event"] == "FIRST_QUESTION"
    assert dumped["result"] is None
    assert dumped["verdict"] is None
