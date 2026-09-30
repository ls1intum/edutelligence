"""Ingest of /artifacts/analysis.json after a read-only analysis session."""

from __future__ import annotations

import json
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


class _Conn:
    def __init__(self):
        self.statements: list[tuple[str, dict]] = []
        self._next_analysis_id = 9
        self._next_workflow_id = 100

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def execute(self, sql, params=None):
        text_sql = " ".join(str(sql).split())
        params = params or {}
        self.statements.append((text_sql, params))
        if "SELECT team_id FROM team_repositories" in text_sql:
            return _Result(7)
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
        return _Result(None)

    async def commit(self):
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
    )
    assert analysis_id == 9

    kinds = [sql for sql, _ in conn.statements]
    assert any("INSERT INTO ai_workflow_analyses" in sql for sql in kinds)
    assert any("INSERT INTO ai_workflows" in sql for sql in kinds)
    rec = next(p for sql, p in conn.statements if "INSERT INTO ai_llm_call_recommendations" in sql)
    assert rec["file_path"] == "src/llm.py"
    assert rec["sla"] == "ux-critical"
    assert rec["workflow_id"] == 100
    assert rec["team_id"] == 7
    assert json.loads(rec["flags"]) == {"night_heavy": False}

    conn2 = _Conn()
    monkeypatch.setattr(db, "sessionmaker", lambda: (lambda: conn2))
    await analysis_ingest.ingest_session({"id": 5, "team_repository_id": 11})
    assert any("INSERT INTO ai_workflows" in sql for sql, _ in conn2.statements)


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
