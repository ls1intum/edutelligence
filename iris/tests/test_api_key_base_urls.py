"""Tests for the base URLs an API key may act for, and for the checks that every route makes of its request.

The Artemis installations that share one Iris are told apart by the base URL that every request names.
A key with ``allowed_base_urls`` is answered only for those installations.
"""

import asyncio
import inspect
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import ValidationError

# The pipelines router pulls in onnxruntime and transformers, which can be absent on some dev
# machines. Stub them only long enough to import the routers (see test_struggle_route).
_stubbed = []
for _mod in ("onnxruntime", "transformers"):
    try:
        __import__(_mod)
    except Exception:  # pylint: disable=broad-exception-caught
        sys.modules[_mod] = MagicMock()
        _stubbed.append(_mod)

from iris import dependencies  # noqa: E402
from iris.common.base_url import normalize_base_url  # noqa: E402
from iris.common.custom_exceptions import (  # noqa: E402
    PermissionDeniedException,
    RequiresAuthenticationException,
)
from iris.config import APIKeyConfig, settings  # noqa: E402
from iris.web.routers import (  # noqa: E402
    faq_census,
    ingestion_census,
    ingestion_status,
    pipelines,
    search,
    webhooks,
)
from iris.web.routers.health import health_endpoint  # noqa: E402

for _mod in _stubbed:
    sys.modules.pop(_mod, None)

OWN = "https://artemis.example.org"
OTHER = "https://other.example.org"

LIMITED_KEY = APIKeyConfig(token="limited", allowed_base_urls=[OWN])
UNLIMITED_KEY = APIKeyConfig(token="unlimited")

ROUTERS = [
    pipelines.router,
    webhooks.router,
    search.router,
    ingestion_status.router,
    ingestion_census.router,
    faq_census.router,
    health_endpoint.router,
]


@pytest.mark.parametrize(
    "value, expected",
    [
        ("https://artemis.example.org", "https://artemis.example.org"),
        ("  https://artemis.example.org  ", "https://artemis.example.org"),
        ("HTTPS://Artemis.Example.ORG", "https://artemis.example.org"),
        ("https://artemis.example.org/", "https://artemis.example.org"),
        ("https://artemis.example.org///", "https://artemis.example.org"),
        ("https://artemis.example.org:443", "https://artemis.example.org"),
        ("http://artemis.example.org:80/", "http://artemis.example.org"),
        ("https://artemis.example.org:8443", "https://artemis.example.org:8443"),
        ("https://artemis.example.org/Artemis/", "https://artemis.example.org/Artemis"),
        ("http://[::1]:8080", "http://[::1]:8080"),
        ("http://localhost:8080", "http://localhost:8080"),
    ],
)
def test_spellings_of_one_base_url_have_one_normal_form(value, expected):
    assert normalize_base_url(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "   ",
        "artemis.example.org",
        "//artemis.example.org",
        "ftp://artemis.example.org",
        "https://",
        "https://user@artemis.example.org",
        "https://user:pass@artemis.example.org",  # pragma: allowlist secret
        "https://artemis.example.org?x=1",
        "https://artemis.example.org/#fragment",
        "https://artemis.example.org#",
        "https://artemis.example.org\\@evil.example",
        "https://artemis.example.org%2f@evil.example",
        "https://evil.example#@artemis.example.org",
        "https://artemis.example.org:notaport",
        "https://artemis.example.org:99999",
    ],
)
def test_a_value_that_is_not_a_base_url_has_no_normal_form(value):
    assert normalize_base_url(value) is None


def test_a_different_host_path_or_port_is_a_different_base_url():
    normal = normalize_base_url(OWN)
    assert normalize_base_url("https://artemis.example.org.evil.example") != normal
    assert normalize_base_url("https://evil.example/artemis.example.org") != normal
    assert normalize_base_url("https://artemis.example.org:8443") != normal
    assert normalize_base_url("https://artemis.example.org/x") != normal
    assert normalize_base_url("http://artemis.example.org") != normal


def test_a_key_without_allowed_base_urls_accepts_every_base_url():
    assert not UNLIMITED_KEY.limits_base_urls()
    assert UNLIMITED_KEY.permits_base_url(OWN)
    assert UNLIMITED_KEY.permits_base_url(OTHER)
    assert UNLIMITED_KEY.permits_base_url(None)


@pytest.mark.parametrize(
    "base_url",
    [OWN, OWN + "/", "HTTPS://ARTEMIS.example.org", "https://artemis.example.org:443"],
)
def test_a_limited_key_accepts_the_spellings_of_its_base_url(base_url):
    assert LIMITED_KEY.limits_base_urls()
    assert LIMITED_KEY.permits_base_url(base_url)


@pytest.mark.parametrize(
    "base_url",
    [
        None,
        "",
        OTHER,
        "https://artemis.example.org.evil.example",
        "http://artemis.example.org",
        "https://artemis.example.org/other",
        "https://artemis.example.org?x=1",
        "https://user@artemis.example.org",
    ],
)
def test_a_limited_key_rejects_every_other_base_url(base_url):
    assert not LIMITED_KEY.permits_base_url(base_url)


def test_a_key_can_be_limited_to_several_base_urls():
    key = APIKeyConfig(token="t", allowed_base_urls=[OWN, OTHER + "/"])
    assert key.permits_base_url(OWN)
    assert key.permits_base_url(OTHER)
    assert not key.permits_base_url("https://third.example.org")


@pytest.mark.parametrize(
    "entry", ["artemis.example.org", "", "ftp://artemis.example.org", "https://a/?q"]
)
def test_a_configured_entry_that_cannot_be_matched_is_refused_at_load(entry):
    with pytest.raises(ValidationError):
        APIKeyConfig(token="t", allowed_base_urls=[entry])


def test_the_example_configuration_loads_without_allowed_base_urls():
    assert all(not key.limits_base_urls() for key in settings.api_keys)


def test_require_base_url_rejects_with_permission_denied():
    dependencies.require_base_url(LIMITED_KEY, OWN)
    dependencies.require_base_url(UNLIMITED_KEY, OTHER)
    with pytest.raises(PermissionDeniedException):
        dependencies.require_base_url(LIMITED_KEY, OTHER)
    with pytest.raises(PermissionDeniedException):
        dependencies.require_base_url(LIMITED_KEY, None)


def test_require_settings_base_url_reads_the_base_url_of_the_settings():
    dependencies.require_settings_base_url(
        LIMITED_KEY, SimpleNamespace(artemis_base_url=OWN)
    )
    with pytest.raises(PermissionDeniedException):
        dependencies.require_settings_base_url(
            LIMITED_KEY, SimpleNamespace(artemis_base_url=OTHER)
        )
    # a request without settings names no installation
    with pytest.raises(PermissionDeniedException):
        dependencies.require_settings_base_url(LIMITED_KEY, None)
    dependencies.require_settings_base_url(UNLIMITED_KEY, None)


# ----------------------------------------------------------------------------- the token validator


def _request(client_host: str | None = "10.0.0.5"):
    return SimpleNamespace(
        client=SimpleNamespace(host=client_host) if client_host else None
    )


@pytest.fixture
def two_keys(monkeypatch):
    first = APIKeyConfig(token="first-token")
    second = APIKeyConfig(token="second-token", allowed_base_urls=[OWN])
    monkeypatch.setattr(settings, "api_keys", [first, second])
    return first, second


def _validate(presented: str, request=None):
    return asyncio.run(dependencies.TokenValidator()(request or _request(), presented))


def test_the_validator_returns_the_key_that_was_presented(two_keys):
    first, second = two_keys
    assert _validate("first-token") is first
    assert _validate("second-token") is second


@pytest.mark.parametrize(
    "presented",
    ["wrong", "first-token ", " first-token", "FIRST-TOKEN", "first-toke", ""],
)
@pytest.mark.usefixtures("two_keys")
def test_the_validator_rejects_a_value_that_is_not_a_key(presented):
    with pytest.raises(PermissionDeniedException):
        _validate(presented)


@pytest.mark.usefixtures("two_keys")
def test_the_validator_rejects_a_request_from_an_unknown_address():
    with pytest.raises(PermissionDeniedException):
        _validate("wrong", _request(None))


@pytest.mark.usefixtures("two_keys")
def test_keys_are_compared_by_digest_in_constant_time():
    with patch.object(
        dependencies.hmac, "compare_digest", wraps=dependencies.hmac.compare_digest
    ) as compare:
        client = _client()
        assert (
            client.get("/api/v1/health/", headers={"Authorization": "x"}).status_code
            == 403
        )
    # one comparison per configured key, whatever the value
    assert compare.call_count == 2


# --------------------------------------------------------------------- every route has a guard


def _api_routes():
    return [
        route
        for router in ROUTERS
        for route in router.routes
        if isinstance(route, APIRoute)
    ]


def _calls_of(dependant):
    for sub in dependant.dependencies:
        yield sub.call
        yield from _calls_of(sub)


def _is_authenticated(route: APIRoute) -> bool:
    return any(
        isinstance(call, dependencies.TokenValidator)
        for call in _calls_of(route.dependant)
    )


# The routes whose request names an Artemis installation, and where each one finds it. A new route
# has to be added here (or to ROUTES_WITHOUT_BASE_URL) so that somebody decides how it is checked.
ROUTES_WITH_BASE_URL = {
    "run_chat_pipeline",
    "run_competency_extraction_pipeline",
    "run_rewriting_pipeline",
    "run_inconsistency_check_pipeline",
    "run_communication_tutor_suggestions_pipeline",
    "run_autonomous_tutor_pipeline",
    "run_struggle_intervention_pipeline",
    "run_global_search_pipeline",
    "lecture_metadata_webhook",
    "lecture_visibility_webhook",
    "lecture_deletion_webhook",
    "faq_ingestion_webhook",
    "faq_deletion_webhook",
    "lecture_search",
    "get_lecture_unit_ingestion_state",
    "get_course_ingestion_census",
    "get_faq_census",
    "health",
}
ROUTES_WITHOUT_BASE_URL = {"get_pipeline"}


def test_every_route_requires_a_key():
    unauthenticated = [
        route.path for route in _api_routes() if not _is_authenticated(route)
    ]
    assert unauthenticated == []


def test_every_route_that_takes_a_base_url_checks_it_against_the_key():
    checked = {
        route.name
        for route in _api_routes()
        if "api_key" in inspect.signature(route.endpoint).parameters
    }
    assert checked == ROUTES_WITH_BASE_URL
    assert {route.name for route in _api_routes()} == (
        ROUTES_WITH_BASE_URL | ROUTES_WITHOUT_BASE_URL
    )


def _settings_of(base_url):
    return None if base_url is None else SimpleNamespace(artemis_base_url=base_url)


def _call_route(name: str, base_url: str | None, key: APIKeyConfig):
    """Call a route function with a request that names ``base_url``, as far as the guard."""
    ids = {"course_id": 1, "lecture_id": 2, "lecture_unit_id": 3}
    match name:
        case "run_chat_pipeline":
            return pipelines.run_chat_pipeline(
                api_key=key,
                event=None,
                dto=SimpleNamespace(settings=_settings_of(base_url)),
            )
        case (
            "run_competency_extraction_pipeline"
            | "run_rewriting_pipeline"
            | "run_inconsistency_check_pipeline"
        ):
            dto = SimpleNamespace(
                execution=SimpleNamespace(settings=_settings_of(base_url))
            )
            return getattr(pipelines, name)(api_key=key, dto=dto)
        case (
            "run_communication_tutor_suggestions_pipeline"
            | "run_autonomous_tutor_pipeline"
            | "run_struggle_intervention_pipeline"
            | "run_global_search_pipeline"
        ):
            dto = SimpleNamespace(settings=_settings_of(base_url))
            return getattr(pipelines, name)(api_key=key, dto=dto)
        case "lecture_metadata_webhook" | "lecture_visibility_webhook":
            return getattr(webhooks, name)(
                api_key=key, dto=SimpleNamespace(base_url=base_url)
            )
        case (
            "lecture_deletion_webhook"
            | "faq_ingestion_webhook"
            | "faq_deletion_webhook"
        ):
            return getattr(webhooks, name)(
                api_key=key, dto=SimpleNamespace(settings=_settings_of(base_url))
            )
        case "lecture_search":
            return search.lecture_search(
                api_key=key,
                dto=SimpleNamespace(
                    artemis_base_url=base_url, query="q", limit=1, course_ids=None
                ),
            )
        case "get_lecture_unit_ingestion_state":
            return ingestion_status.get_lecture_unit_ingestion_state(
                api_key=key, base_url=base_url, **ids
            )
        case "get_course_ingestion_census":
            return ingestion_census.get_course_ingestion_census(
                api_key=key, course_id=1, base_url=base_url
            )
        case "get_faq_census":
            return faq_census.get_faq_census(api_key=key, base_url=base_url)
        case "health":
            headers = {} if base_url is None else {"X-Artemis-Base-Url": base_url}
            return health_endpoint.health(
                request=SimpleNamespace(headers=headers),
                response=SimpleNamespace(),
                api_key=key,
            )
    raise AssertionError(name)


@pytest.mark.parametrize("name", sorted(ROUTES_WITH_BASE_URL))
@pytest.mark.parametrize(
    "base_url", [OTHER, "https://artemis.example.org.evil.example"]
)
def test_a_route_rejects_a_base_url_that_the_key_is_not_allowed_for(name, base_url):
    # nothing may be started or read for the request: the real implementations are not reachable
    with (
        patch("iris.web.routers.pipelines.Thread") as thread,
        patch("iris.web.routers.webhooks.Thread") as webhook_thread,
        patch("iris.web.routers.pipelines._global_search_executor") as executor,
        patch("iris.web.routers.ingestion_census.VectorDatabase") as census_db,
        patch("iris.web.routers.ingestion_status.VectorDatabase") as status_db,
        patch("iris.web.routers.faq_census.VectorDatabase") as faq_db,
        patch("iris.web.routers.search.VectorDatabase") as search_db,
        patch("iris.web.routers.webhooks.VectorDatabase") as webhook_db,
        patch.object(health_endpoint, "MODULES", []),
        patch.object(health_endpoint.ingestion_worker, "register_upstream") as register,
    ):
        with pytest.raises(PermissionDeniedException):
            _call_route(name, base_url, LIMITED_KEY)

    thread.assert_not_called()
    webhook_thread.assert_not_called()
    executor.submit.assert_not_called()
    for database in (census_db, status_db, faq_db, search_db, webhook_db):
        database.assert_not_called()
    register.assert_not_called()


# These routes take the base URL as a required query parameter, and a request cannot leave it out.
ROUTES_WITH_BASE_URL_QUERY_PARAMETER = {
    "get_lecture_unit_ingestion_state",
    "get_course_ingestion_census",
    "get_faq_census",
}


@pytest.mark.parametrize(
    "name",
    sorted(
        ROUTES_WITH_BASE_URL
        - ROUTES_WITH_BASE_URL_QUERY_PARAMETER
        - {"health", "lecture_search"}
    ),
)
def test_a_limited_key_is_rejected_by_a_route_whose_request_names_no_base_url(name):
    with (
        patch("iris.web.routers.pipelines.Thread"),
        patch("iris.web.routers.webhooks.Thread"),
        patch("iris.web.routers.pipelines._global_search_executor"),
    ):
        with pytest.raises(PermissionDeniedException):
            _call_route(name, None, LIMITED_KEY)


def test_a_key_that_is_not_limited_passes_the_check_of_every_route():
    """The check lets an unlimited key through, whatever base URL the request names."""
    for name in ("run_chat_pipeline", "lecture_deletion_webhook", "lecture_search"):
        with (
            patch("iris.web.routers.pipelines.Thread"),
            patch("iris.web.routers.webhooks.Thread"),
            patch("iris.web.routers.pipelines.validate_pipeline_variant"),
            patch("iris.web.routers.webhooks.validate_pipeline_variant"),
            patch("iris.web.routers.search._traced_lecture_search", return_value=[]),
        ):
            _call_route(name, OTHER, UNLIMITED_KEY)


# -------------------------------------------------------------------- through the HTTP stack


def _client() -> TestClient:
    app = FastAPI()
    for router in ROUTERS:
        app.include_router(router)
    return TestClient(app)


STRUGGLE_BODY = {
    "settings": {
        "authenticationToken": "tok",
        "artemisBaseUrl": OWN,
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
        "sessionSeconds": 540,
    },
    "intent": "help_request",
    "episode": {"episodeId": "ep-42", "isNew": True, "hints": []},
}


def _post_struggle(client, token, base_url):
    body = {
        **STRUGGLE_BODY,
        "settings": {**STRUGGLE_BODY["settings"], "artemisBaseUrl": base_url},
    }
    with (
        patch.object(pipelines, "validate_pipeline_variant", return_value="default"),
        patch("iris.web.routers.pipelines.Thread") as thread,
    ):
        response = client.post(
            "/api/v1/pipelines/struggle-intervention/run",
            json=body,
            headers={"Authorization": token},
        )
    return response, thread


@pytest.mark.usefixtures("two_keys")
def test_a_limited_key_runs_a_pipeline_for_its_own_installation_only():
    client = _client()

    own, own_thread = _post_struggle(client, "second-token", OWN)
    assert own.status_code == 202
    own_thread.assert_called_once()

    other, other_thread = _post_struggle(client, "second-token", OTHER)
    assert other.status_code == 403
    other_thread.assert_not_called()

    # a key without a limit is answered for both
    for base_url in (OWN, OTHER):
        response, thread = _post_struggle(client, "first-token", base_url)
        assert response.status_code == 202
        thread.assert_called_once()


@pytest.mark.usefixtures("two_keys")
def test_the_pipeline_variants_need_a_key():
    client = _client()
    with patch.object(pipelines, "LlmManager") as manager:
        manager.return_value.entries = []
        assert client.get("/api/v1/pipelines/CHAT/variants").status_code == 401
        assert (
            client.get(
                "/api/v1/pipelines/CHAT/variants", headers={"Authorization": "wrong"}
            ).status_code
            == 403
        )
        assert (
            client.get(
                "/api/v1/pipelines/CHAT/variants",
                headers={"Authorization": "first-token"},
            ).status_code
            == 200
        )


@pytest.mark.usefixtures("two_keys")
def test_a_health_check_announces_only_the_installation_of_its_key():
    client = _client()
    with (
        patch.object(health_endpoint, "MODULES", []),
        patch.object(health_endpoint.ingestion_worker, "register_upstream") as register,
    ):
        rejected = client.get(
            "/api/v1/health/",
            headers={"Authorization": "second-token", "X-Artemis-Base-Url": OTHER},
        )
        accepted = client.get(
            "/api/v1/health/",
            headers={"Authorization": "second-token", "X-Artemis-Base-Url": OWN + "/"},
        )
        without = client.get(
            "/api/v1/health/", headers={"Authorization": "first-token"}
        )
    assert rejected.status_code == 403
    assert accepted.status_code == 200
    assert without.status_code == 200
    register.assert_called_once_with(OWN + "/", "second-token")


@pytest.mark.usefixtures("two_keys")
def test_a_request_without_a_key_is_not_authenticated():
    request = SimpleNamespace(headers={})
    with pytest.raises(RequiresAuthenticationException):
        dependencies._get_api_key(request)  # pylint: disable=protected-access
