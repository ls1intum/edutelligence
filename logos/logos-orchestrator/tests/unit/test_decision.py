"""Decision models behind POST /v1/systemone."""

import asyncio
import importlib
import json
import math
from unittest.mock import Mock

import httpx
import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse, Response

import logos as main
from logos.dbutils.dbrequest import SystemOneRequest
from logos.pipeline.context_resolver import ContextResolver, ExecutionContext
from logos.routers import user_facing

# ``import logos`` resolves to logos.main in tests, so the submodule is loaded by name.
decision = importlib.import_module("logos.decision")

MODEL = "autotrust/JEV-27B-VL"
PROFILE = decision.PROFILES["autotrust/jev-27b-vl"]


@pytest.fixture(autouse=True)
def _idle_disconnect_watcher(monkeypatch):
    """ASGITransport's ``is_disconnected`` can block the portal; idle until cancel."""

    async def _idle_until_cancelled(request):
        await asyncio.Event().wait()

    monkeypatch.setattr(main, "_wait_for_client_disconnect", _idle_until_cancelled)


def request(questions, state="I was charged twice and want a refund.", model=MODEL):
    return SystemOneRequest.model_validate({"model": model, "state": state, "questions": questions})


def completion(logprobs: dict[int, float], prompt_tokens=50):
    """A vLLM completion carrying the read-out logprobs (tokens as token ids)."""
    top = {f"token_id:{token}": value for token, value in logprobs.items()}
    return {
        "choices": [{"text": "", "logprobs": {"top_logprobs": [top]}}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": 1},
    }


def reference(kind, slot_indices, logprobs):
    """The model card's client-side math: (logprob + bias) / T, then softmax."""
    z = [
        (logprobs.get(PROFILE.verbalizer_ids[i], -1e9) + PROFILE.bias[i]) / PROFILE.temperatures[kind]
        for i in slot_indices
    ]
    e = [math.exp(x - max(z)) for x in z]
    return [x / sum(e) for x in e]


# ── prompt ──────────────────────────────────────────────────────────────────


def test_choice_prompt_labels_each_criterion_with_one_letter():
    body = request(
        {
            "team": {
                "type": "choice",
                "instructions": "Which team should handle this?",
                "criteria": {"billing": "A payment or refund issue", "technical": None},
            }
        }
    )
    compiled = decision.compile_question(PROFILE, body.state, body.questions["team"])
    assert compiled.prompt == (
        "[kind] choice\n[state] I was charged twice and want a refund.\n"
        "[question] Which team should handle this?\n[options]\n"
        "A) billing: A payment or refund issue\nB) technical\n[decision]:"
    )
    assert compiled.keys == ["billing", "technical"]
    assert [PROFILE.verbalizer_ids[i] for i in compiled.slot_indices] == [32, 33]


def test_noul_prompt_lists_the_head_verbalizers_and_explains_criteria():
    body = request(
        {"urgent": {"type": "noul", "instructions": "Needs a reply within the hour?", "criteria": {"true": "Outage"}}}
    )
    compiled = decision.compile_question(PROFILE, {"ticket": "down"}, body.questions["urgent"])
    assert compiled.prompt == (
        '[kind] noul\n[state] {"ticket": "down"}\n[question] Needs a reply within the hour?\ntrue: Outage\n'
        "[options]\nfalse\ntrue\n[decision]:"
    )
    assert [PROFILE.verbalizer_ids[i] for i in compiled.slot_indices] == [3721, 1802]


def test_score_prompt_carries_the_rubric_and_reads_one_slot_per_level():
    body = request({"urgency": {"type": "score", "instructions": "How urgent?", "criteria": ["Can wait", "Today"]}})
    compiled = decision.compile_question(PROFILE, "x", body.questions["urgency"])
    assert "[question] How urgent?\n0: Can wait\n1: Today\n[options]\n0\n1\n[decision]:" in compiled.prompt
    assert compiled.slot_indices == [2, 3]


@pytest.mark.parametrize(
    "question",
    [
        {"type": "choice", "criteria": {"only": None}},
        {"type": "choice", "criteria": {f"o{i}": None for i in range(17)}},
        {"type": "score", "criteria": [str(i) for i in range(7)]},
        {"type": "score", "criteria": ["one"]},
    ],
)
def test_questions_beyond_the_head_are_rejected(question):
    body = request({"q": question})
    with pytest.raises(decision.DecisionError) as exc:
        decision.compile_question(PROFILE, "x", body.questions["q"])
    assert exc.value.status == 422


def test_read_out_restricts_the_next_token_to_the_answer_labels():
    body = request({"q": {"type": "choice", "criteria": {"a": None, "b": None, "c": None}}})
    compiled = decision.compile_question(PROFILE, "x", body.questions["q"])
    payload = decision.completion_payload(MODEL, PROFILE, compiled)
    assert payload["allowed_token_ids"] == [32, 33, 34]
    assert payload["logprobs"] == 3
    assert payload["max_tokens"] == 1
    assert (payload["top_k"], payload["top_p"], payload["temperature"]) == (0, 1.0, 1.0)
    assert payload["return_tokens_as_token_ids"] is True
    assert payload["add_special_tokens"] is False


# ── probabilities ───────────────────────────────────────────────────────────


def test_probabilities_match_the_reference_math():
    body = request({"q": {"type": "choice", "criteria": {"a": None, "b": None, "c": None}}})
    compiled = decision.compile_question(PROFILE, "x", body.questions["q"])
    logprobs = {32: -0.05, 33: -3.2, 34: -5.9}
    got = decision.answer_probabilities(PROFILE, compiled, completion(logprobs))
    assert got == pytest.approx(reference("choice", compiled.slot_indices, logprobs))


def test_a_label_missing_from_the_logprobs_gets_no_probability():
    body = request({"q": {"type": "noul"}})
    compiled = decision.compile_question(PROFILE, "x", body.questions["q"])
    got = decision.answer_probabilities(PROFILE, compiled, completion({1802: -0.01}))
    assert got == pytest.approx([0.0, 1.0])


def test_a_completion_without_logprobs_is_a_bad_gateway():
    body = request({"q": {"type": "noul"}})
    compiled = decision.compile_question(PROFILE, "x", body.questions["q"])
    with pytest.raises(decision.DecisionError) as exc:
        decision.answer_probabilities(PROFILE, compiled, {"choices": [{"text": "x", "logprobs": None}]})
    assert exc.value.status == 502


@pytest.mark.parametrize(
    "top",
    [
        {},
        None,
        {"token_id:99999": -0.1},
        {"token_id:3721": None, "token_id:1802": float("nan")},
    ],
)
def test_empty_or_unmatched_logprobs_are_a_bad_gateway(top):
    """Fallback-only softmax must not become a successful answer distribution."""
    body = request({"q": {"type": "noul"}})
    compiled = decision.compile_question(PROFILE, "x", body.questions["q"])
    completion = {"choices": [{"text": "", "logprobs": {"top_logprobs": [top]}}]}
    with pytest.raises(decision.DecisionError) as exc:
        decision.answer_probabilities(PROFILE, compiled, completion)
    assert exc.value.status == 502


def test_confidence_is_one_minus_the_normalised_entropy():
    # Ollama's published example: these probabilities come with confidence 0.922.
    assert decision.confidence([0.985, 0.012, 0.003]) == pytest.approx(0.922, abs=5e-4)
    assert decision.confidence([0.5, 0.5]) == pytest.approx(0.0)
    assert decision.confidence([1.0, 0.0]) == pytest.approx(1.0)


def test_score_answer_is_the_expected_level():
    body = request({"q": {"type": "score", "criteria": ["low", "mid", "high"]}})
    compiled = decision.compile_question(PROFILE, "x", body.questions["q"])
    answer = decision.build_answer(body.questions["q"], compiled, [0.1, 0.3, 0.6])
    assert answer["score"] == pytest.approx(1.5)
    assert answer["legend"] == {"0": "low", "1": "mid", "2": "high"}
    assert answer["probabilities"] == {"0": 0.1, "1": 0.3, "2": 0.6}


# ── a whole request ─────────────────────────────────────────────────────────


async def test_system_one_asks_every_question_on_the_lora_module():
    body = request(
        {
            "team": {"type": "choice", "criteria": {"billing": None, "technical": None}},
            "urgent": {"type": "noul", "instructions": "Urgent?"},
        }
    )
    sent = []

    async def turn(path, payload):
        sent.append((path, payload, decision.lane_model_override.get()))
        if payload["allowed_token_ids"] == [32, 33]:
            return 200, completion({32: -0.01, 33: -4.6}, prompt_tokens=40)
        return 200, completion({3721: -0.2, 1802: -1.7}, prompt_tokens=30)

    result = await decision.answer_system_one(body, turn)

    assert {path for path, _, _ in sent} == {"v1/completions"}
    assert {override for _, _, override in sent} == {"jev-decision"}
    assert all(payload["model"] == MODEL for _, payload, _ in sent)
    assert decision.lane_model_override.get() is None
    assert result["model"] == MODEL
    assert result["answers"]["team"]["choice"] == "billing"
    assert set(result["answers"]["team"]) == {"type", "choice", "probabilities", "confidence"}
    assert result["answers"]["urgent"]["type"] == "noul"
    assert result["answers"]["urgent"]["noul"] < 0.5
    assert result["usage"] == {"input_tokens": 70, "output_tokens": 2}


async def test_system_one_rejects_a_model_without_a_decision_head():
    with pytest.raises(decision.DecisionError) as exc:
        await decision.answer_system_one(request({"q": {"type": "noul"}}, model="Qwen/Qwen3.8-27B"), None)
    assert exc.value.status == 400


async def test_system_one_passes_a_failed_completion_through():
    async def turn(path, payload):
        return 429, {"error": {"message": "rate limited"}}

    with pytest.raises(decision.DecisionError) as exc:
        await decision.answer_system_one(request({"q": {"type": "noul"}}), turn)
    assert exc.value.status == 429
    assert exc.value.body == {"error": {"message": "rate limited"}}


# ── forwarding ──────────────────────────────────────────────────────────────


def _context(provider_type="logosnode"):
    return ExecutionContext(
        model_id=1,
        provider_id=7,
        provider_name="worker",
        provider_type=provider_type,
        forward_url="ws://worker/v1/completions",
        auth_header="",
        auth_value="",
        model_name=MODEL,
    )


def test_worker_payload_addresses_the_lora_module_only_for_a_read_out():
    _, plain = ContextResolver.prepare_headers_and_payload(_context(), {"model": MODEL})
    token = decision.lane_model_override.set("jev-decision")
    try:
        _, read_out = ContextResolver.prepare_headers_and_payload(_context(), {"model": MODEL})
    finally:
        decision.lane_model_override.reset(token)
    assert plain["model"] == MODEL
    assert read_out["model"] == "jev-decision"


# ── the route ───────────────────────────────────────────────────────────────


async def post(payload):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
        return await client.post("/v1/systemone", json=payload, headers={"Authorization": "Bearer lg-key"})


async def test_route_answers_through_the_pipeline(monkeypatch):
    monkeypatch.setattr(user_facing, "authenticate_api_key", Mock())
    seen = []

    async def handle(path, req):
        seen.append((path, await req.json(), req.headers.get("authorization"), decision.lane_model_override.get()))
        return JSONResponse(completion({3721: -3.0, 1802: -0.05}))

    monkeypatch.setattr(user_facing, "handle_sync_request", handle)
    response = await post({"model": MODEL, "state": {"ticket": "down"}, "questions": {"q": {"type": "noul"}}})

    assert response.status_code == 200
    assert response.json()["answers"]["q"]["noul"] > 0.9
    [(path, sent, auth, override)] = seen
    assert (path, auth, override) == ("v1/completions", "Bearer lg-key", "jev-decision")
    assert json.loads(json.dumps(sent))["allowed_token_ids"] == [3721, 1802]


async def test_route_reports_a_rejected_completion(monkeypatch):
    monkeypatch.setattr(user_facing, "authenticate_api_key", Mock())

    async def handle(path, req):
        raise HTTPException(status_code=403, detail="no access to this model")

    monkeypatch.setattr(user_facing, "handle_sync_request", handle)
    response = await post({"model": MODEL, "state": "x", "questions": {"q": {"type": "noul"}}})
    assert response.status_code == 403
    assert response.json() == {"error": {"message": "no access to this model"}}


async def test_route_reports_an_unreadable_completion_as_bad_gateway(monkeypatch):
    monkeypatch.setattr(user_facing, "authenticate_api_key", Mock())

    async def handle(path, req):
        return Response(content=b"not-json", status_code=200, media_type="text/plain")

    monkeypatch.setattr(user_facing, "handle_sync_request", handle)
    response = await post({"model": MODEL, "state": "x", "questions": {"q": {"type": "noul"}}})
    assert response.status_code == 502
    assert response.json() == {"error": {"message": "The model returned an unreadable response."}}


async def test_route_labels_a_local_bad_gateway_as_api_error(monkeypatch):
    monkeypatch.setattr(user_facing, "authenticate_api_key", Mock())

    async def handle(path, req):
        return JSONResponse({"choices": [{"text": "x", "logprobs": None}]})

    monkeypatch.setattr(user_facing, "handle_sync_request", handle)
    response = await post({"model": MODEL, "state": "x", "questions": {"q": {"type": "noul"}}})
    assert response.status_code == 502
    body = response.json()
    assert body["error"]["type"] == "api_error"
    assert "logprobs" in body["error"]["message"]


async def test_route_labels_an_unknown_model_as_invalid_request(monkeypatch):
    monkeypatch.setattr(user_facing, "authenticate_api_key", Mock())
    response = await post({"model": "not-a-decision-model", "state": "x", "questions": {"q": {"type": "noul"}}})
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_request_error"


async def test_route_rejects_too_many_questions(monkeypatch):
    monkeypatch.setattr(user_facing, "authenticate_api_key", Mock())
    questions = {f"q{i}": {"type": "noul"} for i in range(33)}
    response = await post({"model": MODEL, "state": "x", "questions": questions})
    assert response.status_code == 422


async def test_route_validates_the_question_type(monkeypatch):
    monkeypatch.setattr(user_facing, "authenticate_api_key", Mock())
    response = await post({"model": MODEL, "state": "x", "questions": {"q": {"type": "essay"}}})
    assert response.status_code == 422


async def test_route_rejects_a_bad_key(monkeypatch):
    monkeypatch.setattr(
        user_facing, "authenticate_api_key", Mock(side_effect=HTTPException(status_code=401, detail="Invalid key"))
    )
    response = await post({"model": MODEL, "state": "x", "questions": {"q": {"type": "noul"}}})
    assert response.status_code == 401


async def test_route_cancels_when_the_client_disconnects(monkeypatch):
    """Synthetic pipeline turns cannot see the caller leave; the route must."""
    monkeypatch.setattr(user_facing, "authenticate_api_key", Mock())
    monkeypatch.setattr(user_facing, "get_client_ip", Mock(return_value="127.0.0.1"))
    monkeypatch.setattr(main, "_CLIENT_DISCONNECT_POLL_SECONDS", 0.001)

    async def watch(request):
        while not await request.is_disconnected():
            await asyncio.sleep(0.001)

    monkeypatch.setattr(main, "_wait_for_client_disconnect", watch)
    cancelled = asyncio.Event()

    class LeavingClient:
        headers = {}

        async def is_disconnected(self):
            return True

    async def never_finishes(body, turn):
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr(user_facing, "answer_system_one", never_finishes)
    response = await user_facing.system_one(
        request({"q": {"type": "noul"}}),
        LeavingClient(),
    )

    assert cancelled.is_set()
    assert response.status_code == 499
    assert json.loads(response.body) == {"detail": "Client closed request"}
