"""Iris Response Service: returns the answer of Iris to the last student message of a test case.

Two implementations:
- StubIrisResponseService answers with a fixed text, without calling Iris.
- PyrisIrisResponseService sends the test case to a running Pyris instance, the same way
  Artemis does, and collects the answer from Pyris' status callbacks.
"""

import secrets
import uuid
from typing import Any, Protocol

import requests

from ..evaluation_pipeline.models import TestCase
from .callback_receiver import CallbackReceiver
from .pyris_request import build_chat_request

CHAT_RUN_PATH = "/api/v1/pipelines/chat/run"


class IrisResponseService(Protocol):
    def get_response(self, test_case: TestCase) -> str: ...


class StubIrisResponseService:
    """Answers every test case with the same text, without calling Iris."""

    def get_response(self, test_case: TestCase) -> str:
        return (
            "This is a stub answer. Which part of the problem have you already tried, "
            "and what happened when you ran your code?"
        )


class PyrisIrisResponseService:
    """Gets the answer from a running Pyris instance.

    Flow per test case: build the chat request, POST it to Pyris (answered with 202),
    wait for the status callbacks until FINISHED or FAILED, return the final answer.
    """

    def __init__(
        self,
        pyris_url: str,
        api_token: str,
        timeout: float = 300,
        callback_port: int = 0,
        **settings: Any,  # variant, support_level, selection
    ):
        self.pyris_url = pyris_url.rstrip("/")
        self.api_token = api_token
        self.timeout = timeout
        self.settings = settings
        self.receiver = CallbackReceiver(port=callback_port)
        self.receiver.start()

    def close(self) -> None:
        self.receiver.stop()

    def get_response(self, test_case: TestCase) -> str:
        run_id = f"benchmark-{uuid.uuid4()}"
        callback_token = secrets.token_urlsafe(24)
        self.receiver.register(run_id, callback_token)

        body = build_chat_request(
            test_case,
            callback_base_url=self.receiver.base_url,
            run_id=run_id,
            callback_token=callback_token,
            **self.settings,
        )
        response = requests.post(
            self.pyris_url + CHAT_RUN_PATH,
            json=body,
            headers={"Authorization": self.api_token},
            timeout=30,
        )
        if response.status_code != 202:
            raise RuntimeError(f"Pyris rejected the request ({response.status_code}): {response.text}")

        return _final_answer(self.receiver.wait(run_id, self.timeout))


def _final_answer(updates: list[dict[str, Any]]) -> str:
    """Picks the answer of Iris from the status updates of one run.

    Pyris marks the answer with final=True; intermediate messages have final=False.
    """
    finals = [u["result"] for u in updates if u.get("result") and u.get("final")]
    if finals:
        return finals[-1]
    last = updates[-1] if updates else {}
    if last.get("runState") == "FAILED":
        raise RuntimeError(f"Pyris run failed: {last.get('error')}")
    results = [u["result"] for u in updates if u.get("result")]
    if results:
        return results[-1]
    raise RuntimeError("Pyris finished without an answer")
