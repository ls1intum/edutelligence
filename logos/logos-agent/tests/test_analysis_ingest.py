"""Ingest of /artifacts/analysis.json after a read-only analysis session."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

from app import analysis_ingest, db


class _Result:
    def __init__(self, value=None):
        self._value = value

    def scalar_one(self):
        return self._value

    def scalar_one_or_none(self):
        return self._value

    def mappings(self):
        return self

    def first(self):
        return self._value

    def all(self):
        return self._value or []


class _Conn:
    def __init__(self, *, link_slug: str = "acme/repo", previous=None, analysed_commit=None, decisions=None):
        self.statements: list[tuple[str, dict]] = []
        self.previous = previous or []
        # start_id -> decision row; by default a reviewed row is its own decision.
        self.decisions = decisions
        self.analysed_commit = analysed_commit
        self._next_analysis_id = 9
        self._next_workflow_id = 100
        self._next_step_id = 500
        self.link_slug = link_slug

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def execute(self, sql, params=None):
        text_sql = " ".join(str(sql).split())
        params = params or {}
        self.statements.append((text_sql, params))
        if "WITH RECURSIVE chain" in text_sql:
            if self.decisions is not None:
                return _Result([{"start_id": k, **v} for k, v in self.decisions.items()])
            return _Result([{"start_id": p["id"], **p} for p in self.previous if p["review_status"] != "pending"])
        if "FROM ai_llm_call_recommendations r" in text_sql:
            return _Result([dict(p) for p in self.previous])
        if "SELECT commit_sha FROM ai_workflow_analyses" in text_sql:
            return _Result(self.analysed_commit)
        if "FROM team_repositories" in text_sql and "SELECT" in text_sql:
            return _Result({"team_id": 7, "repo_slug": self.link_slug})
        if "SELECT id FROM ai_workflow_analyses" in text_sql:
            return _Result(None)
        if "INSERT INTO ai_workflow_analyses" in text_sql:
            aid = self._next_analysis_id
            self._next_analysis_id += 1
            return _Result(aid)
        if "INSERT INTO ai_workflows" in text_sql:
            wid = self._next_workflow_id
            self._next_workflow_id += 1
            return _Result(wid)
        if "INSERT INTO ai_workflow_steps" in text_sql:
            sid = self._next_step_id
            self._next_step_id += 1
            return _Result(sid)
        return _Result(None)

    async def commit(self):
        return None

    async def rollback(self):
        return None


def _patch_artifact_root(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        analysis_ingest,
        "settings",
        replace(analysis_ingest.settings, artifact_root=str(tmp_path)),
    )


async def test_ingest_session_marks_failed_when_file_missing(tmp_path, monkeypatch, caplog):
    _patch_artifact_root(monkeypatch, tmp_path)
    conn = _Conn()
    monkeypatch.setattr(db, "sessionmaker", lambda: (lambda: conn))
    session = {"id": 3, "team_repository_id": 11}
    with caplog.at_level("INFO"):
        await analysis_ingest.ingest_session(session)
    assert "left no" in caplog.text or "missing" in caplog.text
    assert any(
        "UPDATE ai_workflow_analyses" in sql and params.get("session_id") == 3 for sql, params in conn.statements
    )


async def test_upsert_analysis_from_temp_json(tmp_path, monkeypatch):
    _patch_artifact_root(monkeypatch, tmp_path)
    session_dir = tmp_path / "5"
    session_dir.mkdir()
    payload = {
        "commit_sha": "abc123",
        "workflows": [
            {
                "name": "chat",
                "trigger_summary": "user message",
                "diagram_mermaid": "flowchart TD\n  A-->B",
                "sort_order": 0,
            }
        ],
        "recommendations": [
            {
                "workflow": "chat",
                "file_path": "src/llm.py",
                "start_line": 10,
                "end_line": 40,
                "recommended_sla": "ux-critical",
                "confidence": 0.9,
                "justification": "interactive",
                "traffic_flags": {"night_heavy": False},
            }
        ],
    }
    (session_dir / "analysis.json").write_text(json.dumps(payload), encoding="utf-8")

    conn = _Conn()
    monkeypatch.setattr(db, "sessionmaker", lambda: (lambda: conn))

    analysis_id = await analysis_ingest.upsert_analysis(
        session_id=5,
        team_repository_id=11,
        payload=payload,
        session_repo_slug="acme/repo",
    )
    assert analysis_id == 9

    kinds = [sql for sql, _ in conn.statements]
    assert any("INSERT INTO ai_workflow_analyses" in sql for sql in kinds)
    assert any("INSERT INTO ai_workflows" in sql for sql in kinds)
    assert any("FOR UPDATE" in sql for sql in kinds)
    wf = next(p for sql, p in conn.statements if "INSERT INTO ai_workflows" in sql)
    assert wf["tag"] is None
    assert not any("INSERT INTO ai_workflow_steps" in sql for sql, _ in conn.statements)
    rec = next(p for sql, p in conn.statements if "INSERT INTO ai_llm_call_recommendations" in sql)
    assert rec["file_path"] == "src/llm.py"
    assert rec["sla"] == "ux-critical"
    assert rec["workflow_id"] == 100
    assert rec["step_id"] is None
    assert rec["team_id"] == 7
    assert json.loads(rec["flags"]) == {"night_heavy": False}
    assert json.loads(rec["priority"]) == ["latency", "quality", "price"]

    conn2 = _Conn()
    monkeypatch.setattr(db, "sessionmaker", lambda: (lambda: conn2))
    await analysis_ingest.ingest_session({"id": 5, "team_repository_id": 11, "repo_slug": "acme/repo"})
    assert any("INSERT INTO ai_workflows" in sql for sql, _ in conn2.statements)


async def test_upsert_persists_workflow_tag_and_steps(monkeypatch):
    payload = {
        "commit_sha": "abc123",
        "workflows": [
            {
                "name": "checkout",
                "trigger_summary": "pay click",
                "diagram_mermaid": "flowchart TD\n  A-->B",
                "sort_order": 0,
                "tag": " Checkout.Pay!! ",
                "steps": [
                    {
                        "name": "score",
                        "sort_order": 0,
                        "tag": "Checkout/Score",
                        "recommended_sla": "ux-critical",
                        "objective_priority": ["latency", "quality"],
                    },
                    {
                        "name": "summarize",
                        "tag": "",
                        "recommended_sla": "ux-background",
                    },
                    {"sort_order": 9},  # nameless → skipped
                ],
            }
        ],
        "recommendations": [
            {
                "workflow": "checkout",
                "step": "score",
                "file_path": "src/pay.py",
                "start_line": 4,
                "recommended_sla": "ux-critical",
            },
            {
                "workflow": "checkout",
                "step": "missing-step",
                "file_path": "src/other.py",
                "start_line": 8,
                "recommended_sla": "ux-high-prio",
            },
        ],
    }
    conn = _Conn()
    monkeypatch.setattr(db, "sessionmaker", lambda: (lambda: conn))
    await analysis_ingest.upsert_analysis(session_id=5, team_repository_id=11, payload=payload)

    wf = next(p for sql, p in conn.statements if "INSERT INTO ai_workflows" in sql)
    assert wf["tag"] == "checkoutpay"
    steps = [p for sql, p in conn.statements if "INSERT INTO ai_workflow_steps" in sql]
    assert len(steps) == 2
    assert steps[0]["name"] == "score"
    assert steps[0]["tag"] == "checkoutscore"
    assert steps[0]["sla"] == "ux-critical"
    assert json.loads(steps[0]["priority"]) == ["latency", "quality", "price"]
    assert steps[0]["sort_order"] == 0
    assert steps[1]["name"] == "summarize"
    assert steps[1]["tag"] is None
    assert steps[1]["sla"] == "ux-background"
    assert steps[1]["sort_order"] == 1

    recs = [p for sql, p in conn.statements if "INSERT INTO ai_llm_call_recommendations" in sql]
    assert recs[0]["step_id"] == 500
    assert recs[0]["workflow_id"] == 100
    assert recs[1]["step_id"] is None


def test_normalize_workflow_tag():
    assert analysis_ingest.normalize_workflow_tag(None) is None
    assert analysis_ingest.normalize_workflow_tag("  ") is None
    assert analysis_ingest.normalize_workflow_tag(" Checkout.Pay ") == "checkoutpay"
    assert analysis_ingest.normalize_workflow_tag("a" * 100) == "a" * 80
    assert analysis_ingest.normalize_workflow_tag("OK-Step_1") == "ok-step1"


async def test_upsert_rejects_obsolete_slug_after_link_edit(tmp_path, monkeypatch, caplog):
    _patch_artifact_root(monkeypatch, tmp_path)
    session_dir = tmp_path / "42"
    session_dir.mkdir()
    payload = {
        "commit_sha": "oldrepo",
        "workflows": [
            {"name": "chat", "trigger_summary": "x", "diagram_mermaid": "flowchart TD\n  A", "sort_order": 0}
        ],
        "recommendations": [],
    }
    (session_dir / "analysis.json").write_text(json.dumps(payload), encoding="utf-8")

    conn = _Conn(link_slug="acme/new")
    monkeypatch.setattr(db, "sessionmaker", lambda: (lambda: conn))
    with caplog.at_level("INFO"):
        await analysis_ingest.ingest_session({"id": 42, "team_repository_id": 11, "repo_slug": "acme/old"})
    assert "obsolete" in caplog.text
    assert not any("INSERT INTO ai_workflow_analyses" in sql for sql, _ in conn.statements)
    assert not any("INSERT INTO ai_workflows" in sql for sql, _ in conn.statements)
    assert any(
        "UPDATE ai_workflow_analyses" in sql and params.get("session_id") == 42 for sql, params in conn.statements
    )


async def test_ingest_rejects_non_object_json(tmp_path, monkeypatch, caplog):
    _patch_artifact_root(monkeypatch, tmp_path)
    conn = _Conn()
    monkeypatch.setattr(db, "sessionmaker", lambda: (lambda: conn))
    path = Path(tmp_path) / "8"
    path.mkdir()
    (path / "analysis.json").write_text("[1,2,3]", encoding="utf-8")
    with caplog.at_level("WARNING"):
        await analysis_ingest.ingest_session({"id": 8, "team_repository_id": 1})
    assert "not an object" in caplog.text
    assert any("UPDATE ai_workflow_analyses" in sql for sql, _ in conn.statements)


async def test_ingest_rejects_sibling_session_symlink(tmp_path, monkeypatch, caplog):
    _patch_artifact_root(monkeypatch, tmp_path)
    victim = tmp_path / "10"
    attacker = tmp_path / "11"
    victim.mkdir()
    attacker.mkdir()
    secret = {"commit_sha": "deadbeef", "workflows": [], "recommendations": []}
    (victim / "analysis.json").write_text(json.dumps(secret), encoding="utf-8")
    (attacker / "analysis.json").symlink_to(victim / "analysis.json")

    conn = _Conn()
    monkeypatch.setattr(db, "sessionmaker", lambda: (lambda: conn))
    with caplog.at_level("WARNING"):
        await analysis_ingest.ingest_session({"id": 11, "team_repository_id": 99})
    assert "unsafe" in caplog.text or "symlink" in caplog.text.lower() or "analysis.json" in caplog.text
    assert not any("INSERT INTO ai_workflows" in sql for sql, _ in conn.statements)
    assert any("UPDATE ai_workflow_analyses" in sql for sql, _ in conn.statements)


async def test_ingest_rejects_oversized_artifact(tmp_path, monkeypatch, caplog):
    _patch_artifact_root(monkeypatch, tmp_path)
    session_dir = tmp_path / "12"
    session_dir.mkdir()
    huge = b"{" + b'"x":"' + (b"a" * (analysis_ingest.MAX_ANALYSIS_BYTES + 10)) + b'"}'
    (session_dir / "analysis.json").write_bytes(huge)
    conn = _Conn()
    monkeypatch.setattr(db, "sessionmaker", lambda: (lambda: conn))
    with caplog.at_level("WARNING"):
        await analysis_ingest.ingest_session({"id": 12, "team_repository_id": 1})
    assert "unsafe" in caplog.text or "exceeds" in caplog.text
    assert any("UPDATE ai_workflow_analyses" in sql for sql, _ in conn.statements)


async def test_ingest_rejects_fifo_without_hanging(tmp_path, monkeypatch, caplog):
    _patch_artifact_root(monkeypatch, tmp_path)
    session_dir = tmp_path / "13"
    session_dir.mkdir()
    fifo = session_dir / "analysis.json"
    os.mkfifo(fifo)
    conn = _Conn()
    monkeypatch.setattr(db, "sessionmaker", lambda: (lambda: conn))
    with caplog.at_level("WARNING"):
        await analysis_ingest.ingest_session({"id": 13, "team_repository_id": 1})
    assert "unsafe" in caplog.text or "regular file" in caplog.text
    assert any("UPDATE ai_workflow_analyses" in sql for sql, _ in conn.statements)


def _previous(**overrides):
    row = {
        "id": 501,
        "file_path": "src/llm.py",
        "start_line": 12,
        "workflow_name": "chat",
        "review_status": "accepted",
        "recommended_sla": "ux-critical",
        "objective_priority": json.dumps(["latency", "quality", "price"]),
        "confirmed_sla": "ux-critical",
        "confirmed_objective_priority": json.dumps(["latency", "quality", "price"]),
        "api_key_id": 33,
        "reviewed_by": 4,
        "reviewed_at": "2026-10-01T10:00:00Z",
        "detected_model": None,
        "model_set_by_owner": False,
    }
    row.update(overrides)
    return row


def _one_rec_payload(**rec):
    return {
        "commit_sha": "def456",
        "workflows": [
            {"name": "chat", "trigger_summary": "x", "diagram_mermaid": "flowchart TD\n  A", "sort_order": 0}
        ],
        "recommendations": [
            {
                "workflow": "chat",
                "file_path": "src/llm.py",
                "start_line": 10,
                "recommended_sla": "ux-critical",
                "detected_model": "gpt-guess",
                **rec,
            }
        ],
    }


async def _ingest_all(monkeypatch, previous, payload, decisions=None):
    conn = _Conn(previous=previous, decisions=decisions)
    monkeypatch.setattr(db, "sessionmaker", lambda: (lambda: conn))
    await analysis_ingest.upsert_analysis(session_id=5, team_repository_id=11, payload=payload)
    return [p for sql, p in conn.statements if "INSERT INTO ai_llm_call_recommendations" in sql]


async def _ingest_with_previous(monkeypatch, previous, payload, decisions=None):
    return (await _ingest_all(monkeypatch, previous, payload, decisions))[0]


async def test_reanalysis_keeps_an_unchanged_decision(monkeypatch):
    rec = await _ingest_with_previous(monkeypatch, [_previous()], _one_rec_payload())
    assert rec["review_status"] == "accepted"
    assert json.loads(rec["confirmed_priority"]) == ["latency", "quality", "price"]
    assert rec["api_key_id"] == 33
    assert rec["previous_id"] == 501
    assert rec["carried_over"] is True


async def test_reanalysis_proposes_a_change_instead_of_overwriting(monkeypatch):
    rec = await _ingest_with_previous(monkeypatch, [_previous()], _one_rec_payload(recommended_sla="ux-background"))
    assert rec["review_status"] == "pending"
    assert rec["confirmed_sla"] is None
    assert rec["api_key_id"] is None
    assert rec["previous_id"] == 501  # the UI shows the previous decision beside the proposal
    assert rec["carried_over"] is False


async def test_reanalysis_keeps_a_rejection_of_the_same_proposal(monkeypatch):
    previous = _previous(review_status="rejected", confirmed_sla=None, confirmed_objective_priority=None)
    rec = await _ingest_with_previous(monkeypatch, [previous], _one_rec_payload())
    assert rec["review_status"] == "rejected"


async def test_reanalysis_keeps_the_model_the_owner_picked(monkeypatch):
    previous = _previous(review_status="pending", detected_model="openai/gpt-oss-120b", model_set_by_owner=True)
    rec = await _ingest_with_previous(monkeypatch, [previous], _one_rec_payload())
    assert rec["detected_model"] == "openai/gpt-oss-120b"
    assert rec["model_set_by_owner"] is True
    assert rec["review_status"] == "pending"


async def test_a_new_call_site_starts_pending_without_a_predecessor(monkeypatch):
    rec = await _ingest_with_previous(monkeypatch, [_previous(file_path="src/other.py")], _one_rec_payload())
    assert rec["review_status"] == "pending"
    assert rec["previous_id"] is None
    assert rec["detected_model"] == "gpt-guess"


async def _ingest_unchanged(tmp_path, monkeypatch, *, claimed, analysed):
    _patch_artifact_root(monkeypatch, tmp_path)
    session_dir = tmp_path / "77"
    session_dir.mkdir()
    (session_dir / "analysis.json").write_text(json.dumps({"unchanged": True, "commit_sha": claimed}), encoding="utf-8")
    conn = _Conn(analysed_commit=analysed)
    monkeypatch.setattr(db, "sessionmaker", lambda: (lambda: conn))
    await analysis_ingest.ingest_session({"id": 77, "team_repository_id": 11, "repo_slug": "acme/repo"})
    return conn


async def test_unchanged_session_is_recorded_as_skipped(tmp_path, monkeypatch):
    conn = await _ingest_unchanged(tmp_path, monkeypatch, claimed="a" * 40, analysed="a" * 40)
    skip = next(sql for sql, _ in conn.statements if "SET status = 'skipped'" in sql)
    # A row recovery already settled (e.g. cancelled mid-finalize) stays as it is.
    assert "AND status IN ('queued', 'running')" in skip
    assert not any("INSERT INTO ai_workflows" in sql for sql, _ in conn.statements)


async def test_unchanged_claim_at_another_commit_is_a_failure(tmp_path, monkeypatch):
    conn = await _ingest_unchanged(tmp_path, monkeypatch, claimed="b" * 40, analysed="a" * 40)
    assert not any("SET status = 'skipped'" in sql for sql, _ in conn.statements)
    assert any("SET status = 'failed'" in sql for sql, _ in conn.statements)


async def test_an_added_call_site_in_the_same_file_does_not_take_the_existing_review(monkeypatch):
    payload = _one_rec_payload()
    payload["workflows"].append({"name": "summary", "diagram_mermaid": "flowchart TD\n  A", "sort_order": 1})
    # The new workflow is listed first and sits nearer the old line.
    payload["recommendations"].insert(
        0, {"workflow": "summary", "file_path": "src/llm.py", "start_line": 12, "recommended_sla": "ux-critical"}
    )
    summary, chat = await _ingest_all(monkeypatch, [_previous()], payload)
    assert chat["review_status"] == "accepted" and chat["previous_id"] == 501
    assert summary["review_status"] == "pending" and summary["previous_id"] is None


async def test_ambiguous_rows_in_one_file_stay_pending(monkeypatch):
    payload = _one_rec_payload(workflow="")
    payload["recommendations"].append({"file_path": "src/llm.py", "start_line": 90, "recommended_sla": "ux-critical"})
    previous = [_previous(workflow_name=None), _previous(id=502, start_line=95, workflow_name=None)]
    recs = await _ingest_all(monkeypatch, previous, payload)
    assert [r["previous_id"] for r in recs] == [None, None]
    assert all(r["review_status"] == "pending" for r in recs)


async def test_the_decision_before_an_unreviewed_proposal_still_counts(monkeypatch):
    # A accepted ux-critical; B proposed ux-background and is still pending; the new
    # analysis proposes ux-critical again -> A's review comes back.
    b_row = _previous(id=601, review_status="pending", confirmed_sla=None, confirmed_objective_priority=None)
    a_decision = {k: v for k, v in _previous(id=600).items() if k not in ("file_path", "start_line", "workflow_name")}
    rec = await _ingest_with_previous(monkeypatch, [b_row], _one_rec_payload(), decisions={601: a_decision})
    assert rec["previous_id"] == 601
    assert rec["review_status"] == "accepted"
    assert rec["api_key_id"] == 33
    assert rec["carried_over"] is True


def test_match_recommendations_prefers_the_same_workflow_then_the_nearest_line():
    previous = [
        {"id": 1, "file_path": "a.py", "workflow_name": "chat", "start_line": 10},
        {"id": 2, "file_path": "a.py", "workflow_name": "chat", "start_line": 50},
    ]
    current = [
        {"file_path": "a.py", "workflow_name": "chat", "start_line": 48},
        {"file_path": "a.py", "workflow_name": "chat", "start_line": 12},
    ]
    matched = analysis_ingest.match_recommendations(previous, current)
    assert {i: m["id"] for i, m in matched.items()} == {0: 2, 1: 1}


def test_an_oversized_group_stays_unmatched_instead_of_building_every_pair(monkeypatch):
    monkeypatch.setattr(analysis_ingest, "MAX_MATCH_PAIRS_PER_GROUP", 4)
    rows = [{"file_path": "a.py", "workflow_name": "chat", "start_line": i} for i in range(3)]
    previous = [{"id": i, **r} for i, r in enumerate(rows)]
    assert analysis_ingest.match_recommendations(previous, rows) == {}  # 3 x 3 > 4: left pending
    assert len(analysis_ingest.match_recommendations(previous[:2], rows[:2])) == 2


def test_matching_ten_thousand_rows_in_one_group_is_cheap():
    rows = [{"file_path": "a.py", "workflow_name": "chat", "start_line": i} for i in range(10_000)]
    previous = [{"id": i, **r} for i, r in enumerate(rows)]
    assert analysis_ingest.match_recommendations(previous, rows) == {}
