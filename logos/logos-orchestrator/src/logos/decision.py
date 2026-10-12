"""Decision models behind the TypeSafe-compatible ``POST /v1/systemone`` endpoint.

A decision model answers typed questions about a state with calibrated
probabilities instead of generated text. Logos serves them on a plain vLLM lane:
the checkpoint carries its decision head as a LoRA module, and one question is
one ``/v1/completions`` call that reads the logprobs of the answer-label tokens
at the first output position (``max_tokens=1``, restricted to those tokens).
Logos adds the head's bias, applies the per-kind temperature and normalises.

Each question runs as its own completion through the normal request pipeline,
so it is authorised, scheduled, logged and billed like any other request; the
questions of one call share the state prefix, which vLLM's prefix cache reuses.
"""

import asyncio
import json
import math
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from logos.dbutils.dbrequest import ChoiceQuestion, DecisionQuestion, NoulQuestion, SystemOneRequest

# The vLLM served name the next worker-bound payload is addressed to, instead of
# the catalogued model name. Set only by this module, for its own completions,
# so a client can never select a lane's LoRA module directly.
lane_model_override: ContextVar[Optional[str]] = ContextVar("lane_model_override", default=None)


@dataclass(frozen=True)
class DecisionProfile:
    """The decision head of one checkpoint: how its answers are read out.

    ``slots`` maps a question kind to its range in ``verbalizer_ids``/``bias``.
    """

    lora_name: str
    verbalizer_ids: tuple[int, ...]
    bias: tuple[float, ...]
    slots: dict[str, tuple[int, int]]
    temperatures: dict[str, float]

    def slot_count(self, kind: str) -> int:
        start, end = self.slots[kind]
        return end - start


# autotrust/JEV-27B-VL at revision ba3f0d584994b37998f235c0a3f6f1beff32ba1e:
# adapter_vllm/decision_head.json and calibration.json ("per_kind").
_JEV_27B_VL = DecisionProfile(
    lora_name="jev-decision",
    verbalizer_ids=(3721, 1802, 15, 16, 17, 18, 19, 20, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47),
    bias=(
        0.00011960109259234741,
        -0.00011981795250903815,
        -0.001826660125516355,
        -0.0008995002135634422,
        1.2772755326295737e-05,
        0.001714941579848528,
        0.0009451315272599459,
        -0.0020803064107894897,
        -0.00017852929886430502,
        -0.00010998119250871241,
        -0.00011865551641676575,
        7.452104182448238e-05,
        -8.196464477805421e-05,
        8.958959369920194e-06,
        -0.002271531615406275,
        -0.0069303084164857864,
        -0.0064850919879972935,
        -0.004779351409524679,
        -0.002676677191630006,
        -0.0025728552136570215,
        -0.002822346054017544,
        -0.002843661466613412,
        -0.0031860454473644495,
        -0.002381357364356518,
    ),
    slots={"noul": (0, 2), "score": (2, 8), "choice": (8, 24)},
    temperatures={"noul": 1.0143134751376188, "choice": 1.0161280671450397, "score": 1.0036213515883572},
)

PROFILES: dict[str, DecisionProfile] = {"autotrust/jev-27b-vl": _JEV_27B_VL}

CHOICE_LABELS = "ABCDEFGHIJKLMNOP"

# Read the whole next-token distribution: the checkpoint's generation defaults
# (top_k=20, top_p=0.95) would otherwise truncate the returned logprobs.
_READ_OUT = {
    "max_tokens": 1,
    "temperature": 1.0,
    "top_p": 1.0,
    "top_k": 0,
    "min_p": 0.0,
    "repetition_penalty": 1.0,
    "add_special_tokens": False,
    "return_tokens_as_token_ids": True,
    "stream": False,
}


class DecisionError(Exception):
    """A request the decision model cannot answer; ``status`` is the HTTP status."""

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status
        self.body: Optional[dict] = None


def profile_for(model: str) -> Optional[DecisionProfile]:
    """The decision profile of a requested model name, if it is a decision model."""
    return PROFILES.get(model.strip().lower())


def _text(value: Any) -> str:
    if value is None:
        return ""
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


@dataclass(frozen=True)
class CompiledQuestion:
    """One question as the checkpoint's prompt plus the slots its answer is read from."""

    kind: str
    prompt: str
    keys: list[str]
    slot_indices: list[int]


def compile_question(profile: DecisionProfile, state: Any, question: DecisionQuestion) -> CompiledQuestion:
    """Render a question in the checkpoint's ``bare-v1`` decision prompt.

    Raises:
        DecisionError: the question needs more answer slots than the head has.
    """
    instructions = _text(question.instructions)
    if isinstance(question, NoulQuestion):
        kind, keys, lines = "noul", ["false", "true"], ["false", "true"]
        criteria = question.criteria
        if criteria is not None and (criteria.true is not None or criteria.false is not None):
            meanings = [f"true: {_text(criteria.true)}" if criteria.true is not None else None]
            meanings.append(f"false: {_text(criteria.false)}" if criteria.false is not None else None)
            instructions = "\n".join([instructions, *[m for m in meanings if m]]).strip()
        start = profile.slots[kind][0]
        slot_indices = [start, start + 1]
    elif isinstance(question, ChoiceQuestion):
        kind, keys = "choice", list(question.criteria)
        if not 2 <= len(keys) <= profile.slot_count(kind):
            raise DecisionError(f"choice questions need 2-{profile.slot_count(kind)} criteria, got {len(keys)}")
        lines = [
            f"{CHOICE_LABELS[i]}) {key}" + (f": {_text(desc)}" if desc is not None else "")
            for i, (key, desc) in enumerate(question.criteria.items())
        ]
        start = profile.slots[kind][0]
        slot_indices = [start + i for i in range(len(keys))]
    else:
        kind = "score"
        levels = len(question.criteria)
        if not 2 <= levels <= profile.slot_count(kind):
            raise DecisionError(f"score questions need 2-{profile.slot_count(kind)} criteria, got {levels}")
        keys = [str(i) for i in range(levels)]
        lines = keys
        rubric = "\n".join(f"{i}: {_text(level)}" for i, level in enumerate(question.criteria))
        instructions = f"{instructions}\n{rubric}".strip()
        start = profile.slots[kind][0]
        slot_indices = [start + i for i in range(levels)]
    prompt = (
        f"[kind] {kind}\n[state] {_text(state)}\n[question] {instructions}\n[options]\n"
        + "\n".join(lines)
        + "\n[decision]:"
    )
    return CompiledQuestion(kind=kind, prompt=prompt, keys=keys, slot_indices=slot_indices)


def completion_payload(model: str, profile: DecisionProfile, compiled: CompiledQuestion) -> dict:
    """The ``/v1/completions`` body that reads one question's answer distribution."""
    ids = [profile.verbalizer_ids[i] for i in compiled.slot_indices]
    return {
        "model": model,
        "prompt": compiled.prompt,
        "logprobs": len(ids),
        "allowed_token_ids": ids,
        **_READ_OUT,
    }


def answer_probabilities(profile: DecisionProfile, compiled: CompiledQuestion, completion: dict) -> list[float]:
    """Calibrated answer probabilities, aligned with ``compiled.keys``.

    Raises:
        DecisionError: the completion carries no logprobs to read (HTTP 502).
    """
    try:
        top = completion["choices"][0]["logprobs"]["top_logprobs"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise DecisionError("the decision model returned no answer logprobs", status=502) from exc
    logprobs: dict[int, float] = {}
    for token, logprob in (top or {}).items():
        _, _, token_id = str(token).rpartition(":")
        if not token_id.isdigit() or logprob is None:
            continue
        value = float(logprob)
        if math.isfinite(value):
            logprobs[int(token_id)] = value
    # At least one requested label must carry a real logprob. An empty or
    # unmatched distribution would otherwise fall through to the -1e9 filler
    # for every label and return a fabricated softmax (HTTP 200). Individually
    # missing labels still get zero probability below.
    if not any(profile.verbalizer_ids[i] in logprobs for i in compiled.slot_indices):
        raise DecisionError("the decision model returned no answer logprobs", status=502)
    temperature = profile.temperatures[compiled.kind]
    logits = [
        (max(logprobs.get(profile.verbalizer_ids[i], -1e9), -1e9) + profile.bias[i]) / temperature
        for i in compiled.slot_indices
    ]
    peak = max(logits)
    weights = [math.exp(x - peak) for x in logits]
    total = sum(weights)
    return [w / total for w in weights]


def confidence(probabilities: list[float]) -> float:
    """One minus the normalised entropy: 1 for a certain answer, 0 for a uniform one."""
    if len(probabilities) < 2:
        return 1.0
    entropy = -sum(p * math.log(p) for p in probabilities if p > 0)
    return max(0.0, 1.0 - entropy / math.log(len(probabilities)))


def build_answer(question: DecisionQuestion, compiled: CompiledQuestion, probabilities: list[float]) -> dict:
    """The TypeSafe answer object for one question."""
    if compiled.kind == "noul":
        return {"type": "noul", "noul": probabilities[1]}
    by_key = dict(zip(compiled.keys, probabilities))
    if compiled.kind == "choice":
        best = max(range(len(probabilities)), key=probabilities.__getitem__)
        return {
            "type": "choice",
            "choice": compiled.keys[best],
            "probabilities": by_key,
            "confidence": confidence(probabilities),
        }
    return {
        "type": "score",
        "score": sum(level * p for level, p in enumerate(probabilities)),
        "legend": {key: level for key, level in zip(compiled.keys, question.criteria)},
        "probabilities": by_key,
        "confidence": confidence(probabilities),
    }


Turn = Callable[[str, dict], Awaitable[tuple[int, Any]]]


async def answer_system_one(body: SystemOneRequest, turn: Turn) -> dict:
    """Answer every question of a ``/v1/systemone`` request.

    ``turn(path, payload)`` runs one request through the pipeline and returns
    ``(status, json body)``.

    Raises:
        DecisionError: the model is no decision model, a question cannot be
            asked, or a completion failed (its status and body are kept).
    """
    profile = profile_for(body.model)
    if profile is None:
        raise DecisionError(f"model '{body.model}' is not a decision model", status=400)
    compiled = {name: compile_question(profile, body.state, q) for name, q in body.questions.items()}

    async def ask(item: CompiledQuestion) -> tuple[list[float], dict]:
        token = lane_model_override.set(profile.lora_name)
        try:
            status, data = await turn("v1/completions", completion_payload(body.model, profile, item))
        finally:
            lane_model_override.reset(token)
        if status != 200:
            error = DecisionError("the decision model request failed", status=status)
            error.body = data if isinstance(data, dict) else None
            raise error
        return answer_probabilities(profile, item, data), (data.get("usage") or {})

    tasks = [asyncio.ensure_future(ask(item)) for item in compiled.values()]
    try:
        results = await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    answers = {}
    input_tokens = output_tokens = 0
    for (name, item), (probabilities, usage) in zip(compiled.items(), results):
        answers[name] = build_answer(body.questions[name], item, probabilities)
        input_tokens += int(usage.get("prompt_tokens") or 0)
        output_tokens += int(usage.get("completion_tokens") or 0)
    return {
        "model": body.model,
        "answers": answers,
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }
