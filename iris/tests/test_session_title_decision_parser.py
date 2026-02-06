import os
from pathlib import Path

os.environ.setdefault(
    "APPLICATION_YML_PATH",
    str(Path(__file__).resolve().parents[1] / "application.example.yml"),
)

from iris.pipeline.abstract_agent_pipeline import AbstractAgentPipeline


def test_parse_session_title_decision_keep():
    assert AbstractAgentPipeline._parse_session_title_decision("KEEP") is None


def test_parse_session_title_decision_update_exact():
    assert (
        AbstractAgentPipeline._parse_session_title_decision(
            "UPDATE: Database Indexing Basics"
        )
        == "Database Indexing Basics"
    )


def test_parse_session_title_decision_update_with_variant_spacing():
    assert (
        AbstractAgentPipeline._parse_session_title_decision(
            "update :  Database Indexing Basics"
        )
        == "Database Indexing Basics"
    )


def test_parse_session_title_decision_update_from_multiline_response():
    llm_out = (
        "I suggest updating the title.\n"
        "UPDATE:  SQL Query Optimization  \n"
        "Reason: The topic changed."
    )
    assert (
        AbstractAgentPipeline._parse_session_title_decision(llm_out)
        == "SQL Query Optimization"
    )


def test_parse_session_title_decision_accepts_german_keywords():
    assert AbstractAgentPipeline._parse_session_title_decision("BEHALTEN") is None
    assert (
        AbstractAgentPipeline._parse_session_title_decision(
            "AKTUALISIEREN: Vektor Datenbanken"
        )
        == "Vektor Datenbanken"
    )


def test_parse_session_title_decision_non_conforming_returns_none():
    assert (
        AbstractAgentPipeline._parse_session_title_decision(
            "The current title is still good."
        )
        is None
    )
