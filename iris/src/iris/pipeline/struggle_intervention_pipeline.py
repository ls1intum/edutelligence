import json
import math
import os
from dataclasses import dataclass
from typing import Callable, List, Optional, cast

from jinja2 import Environment, FileSystemLoader, select_autoescape

from iris.common.logging_config import get_logger
from iris.domain.status.struggle_intervention_status_update_dto import (
    StruggleAction,
    StruggleInterventionStatusUpdateDTO,
)
from iris.domain.struggle.struggle_intervention_pipeline_execution_dto import (
    StruggleInterventionPipelineExecutionDTO,
)
from iris.domain.struggle.struggle_signal_dto import StruggleSignal
from iris.domain.variant.variant import Variant
from iris.pipeline.abstract_agent_pipeline import (
    AbstractAgentPipeline,
    AgentPipelineExecutionState,
)
from iris.tools import (
    create_tool_file_lookup_with_line_numbers,
    create_tool_get_build_logs_analysis,
    create_tool_get_feedbacks,
    create_tool_get_problem_statement,
    create_tool_get_submission_details,
    create_tool_local_vs_submitted_diff,
    create_tool_repository_files,
)
from iris.tracing import observe
from iris.web.status.status_update import StruggleInterventionCallback

logger = get_logger(__name__)


def _extract_json_object(raw: str) -> Optional[dict]:
    """Extract the first JSON object substring from raw and return it parsed, or None on failure."""
    try:
        start, end = raw.index("{"), raw.rindex("}") + 1
        obj = json.loads(raw[start:end])
    except (ValueError, json.JSONDecodeError):
        return None
    return obj if isinstance(obj, dict) else None


def _as_opt_str(v) -> Optional[str]:
    """Return v if it is a non-blank string, else None.

    Blank collapses to None on purpose: "" is not a closing sentence or a fold label, and
    passing it on would only push the empty-vs-missing distinction downstream.
    """
    return v if isinstance(v, str) and v.strip() else None


# The gutter cue is drawn inline after the anchored line of the student's own code, so its
# length is a layout constraint, not a preference: nothing downstream clamps it (the editor
# side only prefixes the lamp), and an overlong cue pushes the line off to the right.
INLINE_HINT_MAX_CHARS = 60


def _clean_inline_hint(raw: str) -> Optional[str]:
    """Make an inlineHint safe to draw straight into the editor gutter, or drop it.

    Two things the prompt asks for but cannot guarantee, both enforced here because this
    value reaches the editor unfiltered:

    - No markdown. The gutter has no markdown pass, so a backtick arrives as a backtick
      next to the code. Observed live before this existed.
    - At most INLINE_HINT_MAX_CHARS. Truncation happens at a word boundary with an ellipsis,
      so a slightly long cue is shortened rather than lost; only a cue with no boundary to
      cut at inside the budget is dropped, since a word cut mid-way reads as a defect.
    """
    cue = raw.replace("`", "").strip()
    if not cue:
        return None
    if len(cue) <= INLINE_HINT_MAX_CHARS:
        return cue
    # Search the full budget, not one char less: a cue whose last space sits exactly at the
    # boundary still has a valid MAX-char form ("x"*59 + "…"), and excluding that position
    # dropped the cue entirely instead of truncating it.
    head = cue[:INLINE_HINT_MAX_CHARS]
    cut = head.rfind(" ")
    return f"{head[:cut].rstrip()}…" if cut > 0 else None


@dataclass
class GateResult:
    action: StruggleAction
    message: Optional[str]
    confidence: float
    rationale: Optional[str]
    anchor: Optional[dict] = None
    inline_hint: Optional[str] = None
    # True when "silent" is the fail-safe for unusable model output, not a decision the model made.
    # The two are otherwise indistinguishable downstream, and on help_request they must not be:
    # the student asked for the hint, so a parse failure has to surface as a failed run.
    parse_failed: bool = False


# A resolved close owes the student two fields. Artemis substitutes its own text when they are
# missing, but that lives in a separate repo on its own deployment schedule and in no part of
# this response contract, so Pyris carries its own fallback and keeps Artemis's as a second net.
CONFIRM_CLOSE_FALLBACK_SENTENCE = "Nice work, that looks resolved."
CONFIRM_CLOSE_FALLBACK_LABEL = "Resolved"
DEGRADED_CLOSE_RATIONALE = "degraded close: model omitted closingSentence/episodeLabel"


@dataclass
class ConfirmCloseResult:
    resolved: bool
    closing_sentence: Optional[str]
    episode_label: Optional[str]
    rationale: Optional[str]
    # True when the close stands but the model did not supply its student-visible fields. Kept
    # separate from the close itself: refusing the close would turn a formatting failure into a
    # substantively unresolved episode, while counting it as an ordinary RECOVERED would let
    # malformed output pass into the evaluation data as a normal recovery.
    degraded: bool = False


def parse_gate_result(raw: Optional[str]) -> GateResult:
    """Parse the LLM's JSON gate decision. Fail safe to silent on any problem."""
    if not raw:
        return GateResult("silent", None, 0.0, None, parse_failed=True)
    obj = _extract_json_object(raw)
    if obj is None:
        return GateResult(
            "silent", None, 0.0, "unparseable model output", parse_failed=True
        )
    action = obj.get("action")
    if action not in ("silent", "ambient", "active"):
        return GateResult("silent", None, 0.0, "invalid action", parse_failed=True)
    message = None
    if action != "silent":
        message = obj.get("message")
        if not isinstance(message, str) or not message.strip():
            return GateResult(
                "silent",
                None,
                0.0,
                "non-silent action without message",
                parse_failed=True,
            )
    raw_confidence = obj.get("confidence", 0.0)
    # bool is a subclass of int, so float(True) is 1.0: `"confidence": true` would arrive as
    # maximum certainty and clear Artemis's confidence threshold for an unsolicited
    # intervention. Same guard the anchor line below already carries.
    if isinstance(raw_confidence, bool):
        confidence = 0.0
    else:
        try:
            confidence = float(raw_confidence)
        except (TypeError, ValueError):
            confidence = 0.0
    if not math.isfinite(confidence):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    rationale = obj.get("rationale")
    if not isinstance(rationale, str):
        rationale = None
    anchor = None
    inline_hint = None
    # Silent means the student sees nothing at all, and the anchor and the inline hint are the
    # two fields that reach them without a chat message: the client draws them in the gutter of
    # the file they are editing. A model that answers `silent` and fills them anyway contradicts
    # itself, so the decision wins and both are dropped here rather than put on the wire.
    if action != "silent":
        raw_anchor = obj.get("anchor")
        raw_line = raw_anchor.get("line") if isinstance(raw_anchor, dict) else None
        # bool is a subclass of int in Python, so guard against `"line": true` masquerading as a line number.
        if (
            isinstance(raw_anchor, dict)
            and isinstance(raw_anchor.get("file"), str)
            and isinstance(raw_line, int)
            and not isinstance(raw_line, bool)
        ):
            anchor = {"file": raw_anchor["file"], "line": raw_line}
        raw_inline_hint = obj.get("inlineHint")
        if isinstance(raw_inline_hint, str):
            # The gutter draws this as plain text, so a backtick reaches the student as a backtick
            # sitting next to their code. The prompt says so, but this field is rendered unfiltered
            # and the prompt has already been wrong about it once, so strip rather than trust.
            inline_hint = _clean_inline_hint(raw_inline_hint)
    return GateResult(action, message, confidence, rationale, anchor, inline_hint)


def parse_confirm_close_result(raw: str) -> ConfirmCloseResult:
    """Parse the LLM's confirmClose JSON. Fail closed to resolved=False on any problem."""
    obj = _extract_json_object(raw)
    if obj is None:
        return ConfirmCloseResult(False, None, None, None)
    resolved = obj.get("resolved")
    if not isinstance(resolved, bool):
        return ConfirmCloseResult(False, None, None, _as_opt_str(obj.get("rationale")))
    if resolved:
        sentence = _as_opt_str(obj.get("closingSentence"))
        label = _as_opt_str(obj.get("episodeLabel"))
        rationale = _as_opt_str(obj.get("rationale"))
        if sentence is None or label is None:
            logger.warning(
                "confirm_close returned resolved=true without %s; using the fallback",
                "closingSentence" if sentence is None else "episodeLabel",
            )
            # rationale is normally empty on a resolved close, so it is free to carry the
            # marker to Artemis and on into the client's evaluation log without a DTO change.
            rationale = (
                f"{DEGRADED_CLOSE_RATIONALE} ({rationale})"
                if rationale
                else DEGRADED_CLOSE_RATIONALE
            )
            return ConfirmCloseResult(
                True,
                sentence or CONFIRM_CLOSE_FALLBACK_SENTENCE,
                label or CONFIRM_CLOSE_FALLBACK_LABEL,
                rationale,
                degraded=True,
            )
        return ConfirmCloseResult(True, sentence, label, rationale)
    return ConfirmCloseResult(False, None, None, _as_opt_str(obj.get("rationale")))


def summarize_signal(signal: StruggleSignal) -> str:
    a = signal.alert
    traj = (
        " ".join(f"(t={t.t:.0f},sBase={t.s:.2f})" for t in signal.trajectory[-6:])
        or "none"
    )
    # TPS is the only boundary whose semantics the LLM cannot infer from the code/build
    # context alone: several consecutive builds without passing any new test - stalled,
    # regressed, or failing outright (the client counts all three as "no progress").
    boundary: str = a.primary_boundary
    if boundary == "TPS":
        boundary = (
            "TPS (test stagnation: several consecutive builds without passing any "
            "new test - stalled, regressed, or failing outright)"
        )
    return (
        f"primary boundary: {boundary}; severity sBase={a.severity:.2f}; "
        f"path={a.path}; "
        f"recent sBase trajectory: {traj}; session {signal.session_seconds:.0f}s."
    )


class StruggleInterventionPipeline(
    AbstractAgentPipeline[StruggleInterventionPipelineExecutionDTO, Variant]
):
    """Proactive second-gate pipeline for the struggle-intervention feature.

    Given a deterministic struggle signal plus the student's code, it decides
    whether a non-spoiler nudge is worthwhile right now and how loudly to deliver
    it (silent | ambient | active), returning the decision via the callback.
    """

    PIPELINE_ID = "struggle_intervention_pipeline"
    ROLES = {"chat"}
    VARIANT_DEFS = [("default", "Default", "Default struggle-intervention variant.")]
    DEPENDENCIES = []

    def __init__(self):
        super().__init__(implementation_id=self.PIPELINE_ID)
        template_dir = os.path.join(os.path.dirname(__file__), "prompts", "templates")
        self.jinja_env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(["html", "xml"]),
        )
        self.system_prompt_template = self.jinja_env.get_template(
            "struggle_intervention_system_prompt.j2"
        )
        self.confirm_close_template = self.jinja_env.get_template(
            "struggle_confirm_close_system_prompt.j2"
        )
        self.help_request_template = self.jinja_env.get_template(
            "struggle_help_request_system_prompt.j2"
        )
        self.tokens = []

    def get_tools(
        self,
        state: AgentPipelineExecutionState[
            StruggleInterventionPipelineExecutionDTO, Variant
        ],
    ) -> List[Callable]:
        submission = state.dto.programming_exercise_submission
        exercise = state.dto.programming_exercise
        callback = state.callback
        tools: List[Callable] = []
        if exercise is not None:
            tools.append(create_tool_get_problem_statement(exercise, callback))
        if submission is not None:
            tools.extend(
                [
                    create_tool_get_submission_details(submission, callback),
                    create_tool_get_build_logs_analysis(submission, callback),
                    create_tool_get_feedbacks(submission, callback),
                    create_tool_repository_files(submission.repository, callback),
                    create_tool_file_lookup_with_line_numbers(
                        submission.repository, callback
                    ),
                    # Dual use, so available for both intents whenever a submission exists: on
                    # decide the diff reveals the code region the student is actively editing
                    # (their current focus); on confirm_close it verifies whether the flagged
                    # issue is fixed in the live working copy vs the last submitted build.
                    create_tool_local_vs_submitted_diff(submission, callback),
                ]
            )
        return tools

    def build_system_message(
        self,
        state: AgentPipelineExecutionState[
            StruggleInterventionPipelineExecutionDTO, Variant
        ],
    ) -> str:
        course = getattr(state.dto, "course", None)
        intent = getattr(state.dto, "intent", "decide")
        tmpl = {
            "decide": self.system_prompt_template,
            "confirm_close": self.confirm_close_template,
            "help_request": self.help_request_template,
        }[intent]
        return tmpl.render(
            course_name=getattr(course, "name", "the course") or "the course",
            signal_summary=summarize_signal(state.dto.struggle_signal),
            episode=state.dto.episode,
            proactivity_mode=getattr(state.dto, "proactivity_mode", "push"),
        )

    def is_memiris_memory_creation_enabled(
        self,
        state: AgentPipelineExecutionState[
            StruggleInterventionPipelineExecutionDTO, Variant
        ],
    ) -> bool:
        return False

    def get_memiris_tenant(self, dto) -> str:
        return ""

    def get_memiris_reference(self, dto) -> str:
        return "unknown"

    def post_agent_hook(
        self,
        state: AgentPipelineExecutionState[
            StruggleInterventionPipelineExecutionDTO, Variant
        ],
    ) -> str:
        cb = state.callback
        status = cast(StruggleInterventionStatusUpdateDTO, cb.status)
        intent = getattr(state.dto, "intent", "decide")
        if intent == "confirm_close":
            cc = parse_confirm_close_result(state.result or "")
            status.resolved = cc.resolved
            status.closing_sentence = cc.closing_sentence
            status.episode_label = cc.episode_label
            status.rationale = cc.rationale
            cb.finish(tokens=state.tokens)
            return cc.closing_sentence or ""
        gate = parse_gate_result(state.result)
        if intent == "help_request" and (gate.parse_failed or gate.action == "silent"):
            # The student explicitly asked for this hint, and the help_request template answers
            # only in "ambient" or "active" - NEVER SILENT is part of that intent's contract.
            # Both an unparseable answer and a contract-violating "silent" finish with an empty
            # result, which reaches Artemis as `result == null` and is delivered as silentDecide:
            # the ask vanishes with no hint and no error. Fail the run for both instead. Artemis
            # completes the client's in-flight request on a terminal FAILED frame, so nothing
            # hangs, and its own tolerance for an incoming "silent" stays what it is, a defensive
            # net rather than a path this side is entitled to use.
            reason = (
                "unusable model output"
                if gate.parse_failed
                else "silent, which this intent forbids"
            )
            logger.warning(
                "help_request produced %s (%s); failing the run", reason, gate.rationale
            )
            status.rationale = gate.rationale
            cb.fail(
                f"Struggle-intervention help request produced {reason}.",
                tokens=state.tokens,
            )
            return ""
        status.action = gate.action
        status.rationale = gate.rationale
        status.anchor_file = gate.anchor["file"] if gate.anchor else None
        status.anchor_line = gate.anchor["line"] if gate.anchor else None
        status.inline_hint = gate.inline_hint
        cb.finish(
            result=gate.message,
            tokens=state.tokens,
            confidence=gate.confidence,
        )
        return gate.message or ""

    @observe(name="Struggle Intervention Pipeline")
    def __call__(
        self,
        dto: StruggleInterventionPipelineExecutionDTO,
        variant: Variant,
        callback: StruggleInterventionCallback,
    ):
        try:
            logger.info("Running struggle-intervention pipeline...")
            local = dto.settings is not None and dto.settings.is_local()
            super().__call__(dto, variant, callback, local=local)
        except Exception as e:  # noqa: BLE001
            logger.error("Error in struggle-intervention pipeline", exc_info=e)
            callback.fail(
                "Error in struggle-intervention pipeline.", tokens=self.tokens
            )
