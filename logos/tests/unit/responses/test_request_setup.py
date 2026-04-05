from logos.responses import request_setup


def test_request_setup_normalizes_azure_cloud_deployments(monkeypatch):
    class DummyDB:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get_deployments_by_profile(self, logos_key, profile_id):  # noqa: ARG002
            return [{"model_id": 10, "provider_id": 1, "type": "cloud"}]

        def get_provider(self, provider_id):  # noqa: ARG002
            return {
                "id": 1,
                "name": "azure",
                "base_url": "https://ase-se01.openai.azure.com/openai/deployments/",
            }

    monkeypatch.setattr("logos.responses.DBManager", DummyDB)

    deployments = request_setup({}, "lg-test", profile_id=7)

    assert deployments == [{"model_id": 10, "provider_id": 1, "type": "azure"}]
