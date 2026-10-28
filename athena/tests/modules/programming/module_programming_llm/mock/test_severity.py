"""Severity validation, persistence, migration, and mocked feedback generation."""

import importlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from athena.database import Base
from athena.models.db_programming_feedback import DBProgrammingFeedback
from athena.schemas import ProgrammingFeedback, TextFeedback, ModelingFeedback


@pytest.mark.parametrize("severity", ["low", "medium", "high", None])
def test_api_database_roundtrip(severity):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    feedback = ProgrammingFeedback(
        exercise_id=1, submission_id=2, severity=severity, credits=0.5
    )
    with Session(engine) as session:
        model = feedback.to_model(lms_url="https://example.org", is_suggestion=True)
        session.add(model)
        session.commit()
        session.expire_all()
        restored = session.get(DBProgrammingFeedback, model.id).to_schema()
        assert restored.model_dump(mode="json", by_alias=True)["severity"] == severity
        assert restored.credits == 0.5
    engine.dispose()


def test_legacy_and_invalid_feedback():
    assert ProgrammingFeedback(exercise_id=1, submission_id=2).severity is None
    with pytest.raises(ValidationError):
        ProgrammingFeedback(exercise_id=1, submission_id=2, severity="critical")
    assert "severity" not in TextFeedback.model_fields
    assert "severity" not in ModelingFeedback.model_fields


def test_existing_database_migration():
    migration = Path(__file__).resolve().parents[5] / "scripts/migrations/001_programming_feedback_severity.sql"
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE programming_feedbacks (id INTEGER PRIMARY KEY, credits FLOAT)"))
        connection.execute(text("INSERT INTO programming_feedbacks VALUES (1, 0.5)"))
        connection.exec_driver_sql(migration.read_text())
        assert connection.execute(text("SELECT credits, severity FROM programming_feedbacks")).one() == (0.5, None)
        connection.execute(text("UPDATE programming_feedbacks SET severity = 'high'"))
        assert connection.execute(text("SELECT severity FROM programming_feedbacks")).scalar_one() == "high"
    engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("graded", [True, False])
async def test_generation_preserves_severity_and_credits(monkeypatch, graded):
    kind = "graded" if graded else "non_graded"
    module = importlib.import_module(f"module_programming_llm.generate_{kind}_suggestions_by_file")
    severities = ["low", "medium", "high", None]
    credits = [0, 0.5, 1, 1]
    items = [module.FeedbackModel(title="Feedback", description="Details", severity=s, credits=c)
             for s, c in zip(severities, credits)]
    # Structured output requires an explicit classification, including null for praise.
    with pytest.raises(ValidationError):
        module.FeedbackModel(title="Missing classification", description="Details")
    with pytest.raises(ValidationError):
        module.FeedbackModel(title="Invalid classification", description="Details", severity="critical")

    repo = SimpleNamespace(working_tree_dir="/repo")
    exercise = SimpleNamespace(
        id=1, max_points=10, bonus_points=0, problem_statement="Implement the task",
        grading_instructions="Grade correctness", grading_criteria=[], programming_language="python",
        get_template_repository=lambda: repo, get_solution_repository=lambda: repo,
    )
    submission = SimpleNamespace(id=2, get_repository=lambda: repo)
    prompt = SimpleNamespace(system_message="system", human_message="human", tokens_before_split=100)
    config = SimpleNamespace(
        generate_suggestions_by_file_prompt=prompt, split_problem_statement_by_file_prompt=prompt,
        split_grading_instructions_by_file_prompt=prompt, max_input_tokens=1000,
        max_number_of_files=25, model=None,
    )
    monkeypatch.setattr(module, "get_chat_prompt", lambda **kwargs: object())
    monkeypatch.setattr(module, "get_diff", lambda **kwargs: "main.py")
    monkeypatch.setattr(module, "load_files_from_repo", lambda *args, **kwargs: {"main.py": "pass"})
    monkeypatch.setattr(module, "num_tokens_from_string", lambda value: 1)
    monkeypatch.setattr(module, "split_problem_statement_by_file", AsyncMock(return_value=None))
    monkeypatch.setattr(module, "check_prompt_length_and_omit_features_if_necessary",
                        lambda **kwargs: (kwargs["prompt_input"], True))
    if graded:
        monkeypatch.setattr(module, "split_grading_instructions_by_file", AsyncMock(return_value=None))
    else:
        monkeypatch.setattr(module, "generate_summary_by_file", AsyncMock(return_value=None))
        monkeypatch.setattr(module, "format_grading_instructions", lambda *args: "Grade correctness")
    predict = AsyncMock(return_value=SimpleNamespace(feedbacks=items))
    monkeypatch.setattr(module, "predict_and_parse", predict)

    result = await module.generate_suggestions_by_file(exercise, submission, config, False)
    assert [f.severity for f in result] == severities
    assert [f.credits for f in result] == (credits if graded else [0, 1.25, 2.5, 2.5])
    assert all(f.is_graded == graded for f in result)
    predict.assert_awaited_once()
