"""Run one study situation through production Iris and store the result.

Usage (from the iris/ folder, see run_matrix.py for the environment):
  run_one.py SCENARIO_JSON LABEL SELECTION VARIANT OUT_JSON

APPLICATION_YML_PATH and LLM_CONFIG_PATH point at the configuration's files.
The result keeps the judge input for later blind judging; it never calls a judge.
"""

import json
import sys
import time
import traceback
from pathlib import Path
from types import SimpleNamespace

# Model ids that may answer a LOCAL_AI run. Anything else means a local run
# reached a cloud model.
OPEN_MODELS = (
    "Qwen/",
    "bench-gpt-oss",
    "bench-gemma",
    "openai/gpt-oss",
    "google/gemma",
)


def main() -> int:
    scenario_path, label, selection, variant, out_path = sys.argv[1:6]
    # pylint: disable=import-outside-toplevel,unused-import
    import iris.pipeline.pipeline  # noqa: F401  production import order
    from iris.config import settings
    from iris.qa.schema import Scenario
    from iris.qa.worker import _run_pipeline, build_judge_request

    # pylint: enable=import-outside-toplevel,unused-import
    result: dict = {"config": label, "selection": selection, "variant": variant}
    started = time.monotonic()
    try:
        if selection == "LOCAL_AI" and not settings.local_llm_enabled:
            raise RuntimeError(
                "local_llm_enabled is false: a local run would use cloud models"
            )
        scenario = Scenario.model_validate_json(
            Path(scenario_path).read_text(encoding="utf-8")
        )
        result["scenarioId"] = scenario.id
        scenario.payload["settings"].update(
            selection=selection,
            variant=variant,
            streamResponse=True,  # Artemis default (artemis.iris.response-streaming-enabled)
            runId=f"study-{label}-{scenario.id}",
        )
        # Production limits, not the harness's tighter per-scenario cost guard.
        scenario.token_ceiling = SimpleNamespace(
            max_agent_turns=15,
            max_input_tokens=800_000,
            max_output_tokens=120_000,
            max_output_tokens_per_call=16_000,
        )
        # An empty candidate model makes the harness route like production.
        run = _run_pipeline(scenario, "")  # pylint: disable=protected-access
        result.update(run)
        calls = run["telemetry"]["modelCalls"]
        if selection == "LOCAL_AI":
            foreign = sorted(
                {c["model"] for c in calls if not c["model"].startswith(OPEN_MODELS)}
            )
            if foreign:
                raise RuntimeError(f"Local run called non-open models: {foreign}")
        result["judgeInput"] = build_judge_request(
            scenario, run["response"], run["activities"], run["diagnostics"]
        )
        result["executionError"] = None
    except Exception as error:  # pylint: disable=broad-exception-caught
        result["executionError"] = f"{type(error).__name__}: {str(error)[:600]}"
        result["traceback"] = traceback.format_exc()[-4000:]
    result["seconds"] = round(time.monotonic() - started, 2)
    Path(out_path).write_text(
        json.dumps(result, indent=1, default=str, ensure_ascii=False), encoding="utf-8"
    )
    return 0 if not result["executionError"] else 1


if __name__ == "__main__":
    sys.exit(main())
