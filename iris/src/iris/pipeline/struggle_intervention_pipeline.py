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
    create_tool_file_lookup,
    create_tool_get_build_logs_analysis,
    create_tool_get_feedbacks,
    create_tool_get_problem_statement,
    create_tool_get_submission_details,
    create_tool_repository_files,
)
from iris.tracing import observe
from iris.web.status.status_update import StruggleInterventionCallback

logger = get_logger(__name__)


@dataclass
class GateResult:
    action: StruggleAction
    message: Optional[str]
    confidence: float
    rationale: Optional[str]
    anchor: Optional[dict] = None
    inline_hint: Optional[str] = None


def parse_gate_result(raw: Optional[str]) -> GateResult:
    """Parse the LLM's JSON gate decision. Fail safe to silent on any problem."""
    if not raw:
        return GateResult("silent", None, 0.0, None)
    try:
        start, end = raw.index("{"), raw.rindex("}") + 1
        obj = json.loads(raw[start:end])
    except (ValueError, json.JSONDecodeError):
        return GateResult("silent", None, 0.0, "unparseable model output")
    if not isinstance(obj, dict):
        return GateResult("silent", None, 0.0, "unparseable model output")
    action = obj.get("action")
    if action not in ("silent", "ambient", "active"):
        return GateResult("silent", None, 0.0, "invalid action")
    message = None
    if action != "silent":
        message = obj.get("message")
        if not isinstance(message, str) or not message.strip():
            return GateResult("silent", None, 0.0, "non-silent action without message")
    try:
        confidence = float(obj.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    if not math.isfinite(confidence):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    rationale = obj.get("rationale")
    if not isinstance(rationale, str):
        rationale = None
    anchor = None
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
    inline_hint = obj.get("inlineHint")
    if not isinstance(inline_hint, str) or not inline_hint.strip():
        inline_hint = None
    return GateResult(action, message, confidence, rationale, anchor, inline_hint)


def summarize_signal(signal: StruggleSignal) -> str:
    a = signal.alert
    comps = (
        ", ".join(f"{c.name}={c.value:.2f}" for c in signal.dominant_components)
        or "none"
    )
    traj = (
        " ".join(f"(t={t.t:.0f},v={t.v:.2f})" for t in signal.trajectory[-6:]) or "none"
    )
    return (
        f"primary boundary: {a.primary_boundary}; severity v={a.severity:.2f}; "
        f"path={a.path}; dominant components: {comps}; "
        f"recent v-trajectory: {traj}; session {signal.session_seconds:.0f}s."
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
            autoescape=select_autoescape(["html", "xml", "j2"]),
        )
        self.system_prompt_template = self.jinja_env.get_template(
            "struggle_intervention_system_prompt.j2"
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
                    create_tool_file_lookup(submission.repository, callback),
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
        return self.system_prompt_template.render(
            {
                "course_name": getattr(course, "name", "the course") or "the course",
                "signal_summary": summarize_signal(state.dto.struggle_signal),
            }
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
        gate = parse_gate_result(state.result)
        cb = state.callback
        status = cast(StruggleInterventionStatusUpdateDTO, cb.status)
        status.action = gate.action
        status.rationale = gate.rationale
        status.anchor_file = gate.anchor["file"] if gate.anchor else None
        status.anchor_line = gate.anchor["line"] if gate.anchor else None
        status.inline_hint = gate.inline_hint
        cb.done(
            "Decision made",
            final_result=gate.message,
            tokens=self.tokens,
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
            callback.error(
                "Error in struggle-intervention pipeline.", tokens=self.tokens
            )
