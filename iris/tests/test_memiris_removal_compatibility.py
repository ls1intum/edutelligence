"""Iris still accepts what deployments and Artemis versions from before the Memiris removal send it."""

from pathlib import Path

import yaml

import iris.pipeline.pipeline  # noqa: F401  pylint: disable=unused-import
from iris.config import Settings
from iris.domain.data.user_dto import UserDTO
from iris.domain.status.chat_status_update_dto import ChatStatusUpdateDTO
from iris.domain.status.run_state_dto import RunStateEnum

APPLICATION_EXAMPLE = Path(__file__).resolve().parent.parent / "application.example.yml"


def test_an_application_yml_that_still_configures_memiris_loads():
    config = yaml.safe_load(APPLICATION_EXAMPLE.read_text())
    config["memiris"] = {
        "enabled": True,
        "sleep_enabled": True,
        "llm_configuration": {"embeddings": ["some-embedding-model"]},
    }

    settings = Settings.model_validate(config)

    assert not hasattr(settings, "memiris")


def test_a_user_sent_by_an_older_artemis_with_its_memiris_flag_parses():
    user = UserDTO.model_validate(
        {"id": 7, "firstName": "Ada", "memirisEnabled": True, "langKey": "de"}
    )

    assert user.id == 7
    assert user.lang_key == "de"


def test_a_chat_status_update_no_longer_carries_memory_fields():
    payload = ChatStatusUpdateDTO(
        run_state=RunStateEnum.FINISHED, result="answer"
    ).model_dump(by_alias=True)

    assert "accessedMemories" not in payload
    assert "createdMemories" not in payload
