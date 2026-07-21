from __future__ import annotations

import argparse
import json
from pathlib import Path

# pylint: disable=import-outside-toplevel


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    raw = json.loads(Path(args.input).read_text(encoding="utf-8"))

    from iris.qa.schema import Scenario
    from iris.qa.worker import _judge

    scenario = Scenario.model_validate(raw["scenario"])
    activities = [
        {"name": name, "state": "FINISHED"} for name in raw.get("activities", [])
    ]
    result = _judge(
        scenario,
        raw.get("answer"),
        activities,
        diagnostics=raw.get("diagnostics"),
    )
    Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
