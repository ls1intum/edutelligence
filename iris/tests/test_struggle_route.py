# Tests the route registration + the worker directly, avoiding the auth
# dependency (Depends(TokenValidator()) with a nested api-key dependency that
# is brittle to patch via a TestClient).
import sys
from unittest.mock import MagicMock, patch

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
