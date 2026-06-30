# Tests the route registration + the worker directly.
# The confirm_close smoke test uses FastAPI TestClient with the real auth dependency
# (the "secret" token present in application.example.yml, loaded by conftest.py).
import sys
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

# GlobalSearchPipeline (imported transitively via the pipelines router) pulls in
# the heavy native deps onnxruntime + transformers, which can be absent on some
# dev machines. Use the real modules when importable; otherwise stub them just
# long enough to import the router, then drop the stubs so no other test in the
# session ever sees a fake in their place. numpy/joblib are always installed and
# must never be stubbed.
_stubbed = []
for _mod in ("onnxruntime", "transformers"):
    try:
        __import__(_mod)
    except Exception:  # pylint: disable=broad-exception-caught
        sys.modules[_mod] = MagicMock()
        _stubbed.append(_mod)

from iris.web.routers import pipelines  # noqa: E402

for _mod in _stubbed:
    sys.modules.pop(_mod, None)


def test_struggle_route_is_registered():
    paths = {r.path for r in pipelines.router.routes}
    assert "/api/v1/pipelines/struggle-intervention/run" in paths


def test_worker_invokes_pipeline_with_callback():
    dto = MagicMock()
    dto.settings.authentication_token = "job-1"
    dto.settings.artemis_base_url = "http://localhost:8080"
    dto.initial_stages = []
    with patch.object(pipelines, "StruggleInterventionCallback") as cb, patch.object(
        pipelines, "StruggleInterventionPipeline"
    ) as pipe, patch.object(
        pipelines, "find_variant", return_value="v"
    ) as find_variant:
        pipelines.run_struggle_intervention_pipeline_worker(dto, "default", "req-1")
    cb.assert_called_once_with(
        run_id="job-1", base_url="http://localhost:8080", initial_stages=[]
    )
    find_variant.assert_called_once_with(pipe.get_variants.return_value, "default")
    pipe.return_value.assert_called_once_with(
        dto=dto, variant="v", callback=cb.return_value
    )


def test_confirm_close_intent_routes_without_422():
    """Smoke: a confirm_close body validates (no 422) and the worker receives
    dto.intent == 'confirm_close'.

    Auth passes via the 'secret' token configured in application.example.yml,
    which conftest.py wires as APPLICATION_YML_PATH before any settings load.
    validate_pipeline_variant and Thread are both mocked to avoid LLM/network I/O.
    """
    test_app = FastAPI()
    test_app.include_router(pipelines.router)
    client = TestClient(test_app)

    payload = {
        "settings": {
            "authenticationToken": "tok",
            "artemisBaseUrl": "http://localhost:8080",
            "variant": "default",
        },
        "struggleSignal": {
            "alert": {
                "tSessionS": 540,
                "primaryBoundary": "FM",
                "boundaryTypes": ["FM"],
                "severity": 0.7,
                "path": "armed",
                "inWarmup": False,
                "inGrace": False,
            },
            "trajectory": [],
            "dominantComponents": [],
            "sessionSeconds": 540,
        },
        "intent": "confirm_close",
        "episode": {"episodeId": "ep-42", "isNew": True, "hints": []},
    }

    with patch.object(
        pipelines, "validate_pipeline_variant", return_value="default"
    ), patch("iris.web.routers.pipelines.Thread") as thread_cls:
        resp = client.post(
            "/api/v1/pipelines/struggle-intervention/run",
            json=payload,
            headers={"Authorization": "secret"},
        )

    assert resp.status_code == 202
    thread_cls.assert_called_once()
    dto_arg = thread_cls.call_args.kwargs["args"][0]
    assert dto_arg.intent == "confirm_close"
