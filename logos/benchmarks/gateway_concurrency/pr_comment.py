#!/usr/bin/env python
"""Post/update a PR comment with the gateway concurrency benchmark's numbers.

Informational only, unlike ``per_request_overhead/pr_comment.py`` — no
``--check`` gate, no exit-code-as-CI-failure. There is no baseline yet to
set a pass/fail threshold against.

Stdlib only, so it runs from the plain benchmark venv.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from report import build_markdown  # noqa: E402

_ANCHOR = "<!-- logos-gateway-concurrency-bench -->"
_API_TIMEOUT_S = 30.0


def _load_result() -> Dict[str, Any]:
    out_dir = Path(os.environ.get("LOGOS_BENCH_GW_OUTPUT") or (_HERE / "reports"))
    result_path = out_dir / "result.json"
    if not result_path.exists():
        raise FileNotFoundError(f"benchmark result not found: {result_path}")
    return json.loads(result_path.read_text())


def _api_request(method: str, url: str, token: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=_API_TIMEOUT_S) as response:
        body = response.read().decode()
        return json.loads(body) if body else {}


def _pr_number() -> Optional[str]:
    explicit = os.environ.get("LOGOS_BENCH_PR_NUMBER")
    if explicit:
        return explicit
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path or not Path(event_path).exists():
        return None
    event = json.loads(Path(event_path).read_text())
    number = event.get("number") or (event.get("pull_request") or {}).get("number")
    return str(number) if number else None


def _find_last_bench_comment(api_comments: str, token: str) -> Optional[Dict[str, Any]]:
    page = 1
    while True:
        comments = _api_request("GET", f"{api_comments}?per_page=100&page={page}", token)
        if not comments:
            return None
        matching = [c for c in comments if _ANCHOR in (c.get("body") or "")]
        if matching:
            return matching[-1]
        if len(comments) < 100:
            return None
        page += 1


def _post_comment(markdown: str) -> None:
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    server = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    number = _pr_number()
    if not token or not repo or not number:
        print("PR comment skipped (no GITHUB_TOKEN / GITHUB_REPOSITORY / PR number)")
        return
    api_comments = f"{server}/repos/{repo}/issues/{number}/comments"
    existing = _find_last_bench_comment(api_comments, token)
    if existing:
        _api_request("PATCH", f"{server}/repos/{repo}/issues/comments/{existing['id']}", token, {"body": markdown})
        print(f"PR comment updated (id={existing['id']})")
    else:
        _api_request("POST", api_comments, token, {"body": markdown})
        print("PR comment created")


def main() -> int:
    try:
        result = _load_result()
    except FileNotFoundError as exc:
        print(f"PR comment skipped ({exc})")
        return 0
    markdown = build_markdown(result) + f"\n{_ANCHOR}\n"
    if os.environ.get("LOGOS_BENCH_PR_COMMENT_DRY_RUN") == "1":
        print(markdown)
        return 0
    try:
        _post_comment(markdown)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
        # Fork PRs run read-only: the uploaded artifact still carries the numbers.
        print(f"PR comment failed (continuing): {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
