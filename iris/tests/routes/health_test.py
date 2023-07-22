import pytest
import app.config as config


@pytest.fixture(scope="function")
def model_configs():
    llm_model_config1 = config.LLMModelConfig(
        name="test1", description="test", llm_credentials={}
    )
    llm_model_config2 = config.LLMModelConfig(
        name="test2", description="test", llm_credentials={}
    )
    llm_model_config3 = config.LLMModelConfig(
        name="test3", description="test", llm_credentials={}
    )
    config.settings.pyris.llms = {
        "GPT35_TURBO": llm_model_config1,
        "GPT35_TURBO_16K_0613": llm_model_config2,
        "GPT35_TURBO_0613": llm_model_config3,
    }


@pytest.mark.usefixtures("model_configs")
def test_checkhealth(test_client, headers, mocker):
    objA = mocker.Mock()
    objB = mocker.Mock()
    objC = mocker.Mock()

    def side_effect_func(*_, **kwargs):
        if kwargs["model"] == config.settings.pyris.llms["GPT35_TURBO"]:
            return objA
        elif (
            kwargs["model"]
            == config.settings.pyris.llms["GPT35_TURBO_16K_0613"]
        ):
            return objB
        elif kwargs["model"] == config.settings.pyris.llms["GPT35_TURBO_0613"]:
            return objC

    mocker.patch(
        "app.services.guidance_wrapper.GuidanceWrapper.__new__",
        side_effect=side_effect_func,
    )
    mocker.patch.object(objA, "is_up", return_value=True)
    mocker.patch.object(objB, "is_up", return_value=False)
    mocker.patch.object(objC, "is_up", return_value=True)

    response = test_client.get("/api/v1/health", headers=headers)
    assert response.status_code == 200
    assert response.json() == [
        {"model": "GPT35_TURBO", "status": "UP"},
        {"model": "GPT35_TURBO_16K_0613", "status": "DOWN"},
        {"model": "GPT35_TURBO_0613", "status": "UP"},
    ]

    # Assert the second call is cached
    test_client.get("/api/v1/health", headers=headers)
    objA.is_up.assert_called_once()
    objB.is_up.assert_called_once()
    objC.is_up.assert_called_once()


@pytest.mark.usefixtures("model_configs")
def test_checkhealth_save_to_cache(
    test_client, test_cache_store, headers, mocker
):
    objA = mocker.Mock()
    objB = mocker.Mock()
    objC = mocker.Mock()

    def side_effect_func(*_, **kwargs):
        if kwargs["model"] == config.settings.pyris.llms["GPT35_TURBO"]:
            return objA
        elif (
            kwargs["model"]
            == config.settings.pyris.llms["GPT35_TURBO_16K_0613"]
        ):
            return objB
        elif kwargs["model"] == config.settings.pyris.llms["GPT35_TURBO_0613"]:
            return objC

    mocker.patch(
        "app.services.guidance_wrapper.GuidanceWrapper.__new__",
        side_effect=side_effect_func,
    )
    mocker.patch.object(objA, "is_up", return_value=True)
    mocker.patch.object(objB, "is_up", return_value=False)
    mocker.patch.object(objC, "is_up", return_value=True)

    assert test_cache_store.get("GPT35_TURBO:status") is None
    assert test_cache_store.get("GPT35_TURBO_16K_0613:status") is None
    assert test_cache_store.get("GPT35_TURBO_0613:status") is None

    test_client.get("/api/v1/health", headers=headers)

    assert test_cache_store.get("GPT35_TURBO:status") == "CLOSED"
    assert test_cache_store.get("GPT35_TURBO_16K_0613:status") == "OPEN"
    assert test_cache_store.get("GPT35_TURBO_0613:status") == "CLOSED"


def test_checkhealth_with_wrong_api_key(test_client):
    headers = {"Authorization": "wrong api key"}
    response = test_client.get("/api/v1/health", headers=headers)
    assert response.status_code == 403
    assert response.json()["detail"] == {
        "type": "not_authorized",
        "errorMessage": "Permission denied",
    }


def test_checkhealth_without_authorization_header(test_client):
    response = test_client.get("/api/v1/health")
    assert response.status_code == 401
    assert response.json()["detail"] == {
        "type": "not_authenticated",
        "errorMessage": "Requires authentication",
    }
