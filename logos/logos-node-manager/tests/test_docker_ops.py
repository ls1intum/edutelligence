"""The exact command lines and the parsing of what Docker prints."""

from __future__ import annotations

import json

import pytest

from logos_node_manager.docker_ops import Docker, describe_registry_login, split_image_ref
from logos_node_manager.errors import DockerError
from logos_node_manager.runner import CommandResult


class FakeRunner:
    """Hands out scripted results and remembers what it was asked."""

    def __init__(self, *results: CommandResult) -> None:
        self.results = list(results)
        self.calls: list[tuple[tuple[str, ...], float, dict[str, str]]] = []

    def run(self, argv, *, timeout_s, env=None):
        self.calls.append((tuple(argv), timeout_s, dict(env or {})))
        return self.results.pop(0)


def ok(stdout: str = "") -> CommandResult:
    return CommandResult(("x",), 0, stdout=stdout)


def failed(stderr: str, code: int = 1) -> CommandResult:
    return CommandResult(("x",), code, stderr=stderr)


def docker_with(settings, *results: CommandResult) -> tuple[Docker, FakeRunner]:
    runner = FakeRunner(*results)
    return Docker(settings, runner), runner


def inspect_json(**state) -> str:
    container = {
        "Id": "abc123",
        "Image": "sha256:img",
        "Config": {"Image": "registry.example/logos/logos-workernode-vllm:latest"},
        "RestartCount": 0,
        "State": {"Status": "running", "Running": True, "Restarting": False, "ExitCode": 0, **state},
    }
    return json.dumps([container])


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        ("registry.example/logos/worker:latest", ("registry.example/logos/worker", "latest")),
        ("localhost:5001/dummy-worker:v2", ("localhost:5001/dummy-worker", "v2")),
        ("localhost:5001/dummy-worker", ("localhost:5001/dummy-worker", None)),
        ("worker", ("worker", None)),
        ("worker:pr-1187", ("worker", "pr-1187")),
        ("registry.example/worker:v1@sha256:abc", ("registry.example/worker", "v1")),
        ("registry.example/worker@sha256:abc", ("registry.example/worker", None)),
    ],
)
def test_image_references_are_split_into_name_and_tag(ref, expected):
    assert split_image_ref(ref) == expected


def test_pull_names_the_project_files_and_only_the_worker_service(settings):
    docker, runner = docker_with(settings, ok())

    docker.pull("v2")

    argv, timeout_s, _ = runner.calls[0]
    assert argv == (
        "docker",
        "compose",
        "-p",
        settings.project_name,
        "-f",
        str(settings.compose_file),
        "--env-file",
        str(settings.env_file),
        "pull",
        "logos-workernode",
    )
    assert timeout_s == settings.pull_timeout_s


def test_the_requested_tag_overrides_the_env_file_through_the_process_environment(settings):
    docker, runner = docker_with(settings, ok(), ok())

    docker.pull("v2")
    docker.up("v2")

    assert [call[2] for call in runner.calls] == [{"IMAGE_TAG": "v2"}, {"IMAGE_TAG": "v2"}]


def test_up_touches_only_the_worker_service(settings):
    docker, runner = docker_with(settings, ok())

    docker.up("v2")

    assert runner.calls[0][0][-4:] == ("up", "-d", "--no-deps", "logos-workernode")


def test_a_rollback_forces_the_recreate_and_never_pulls(settings):
    docker, runner = docker_with(settings, ok())

    docker.up("latest", recreate=True, pull_never=True)

    assert runner.calls[0][0][-7:] == (
        "up",
        "-d",
        "--no-deps",
        "--force-recreate",
        "--pull",
        "never",
        "logos-workernode",
    )


def test_the_image_reference_comes_from_compose_without_printing_the_environment(settings):
    docker, runner = docker_with(settings, ok("registry.example/logos/logos-workernode-vllm:v2\n"))

    ref = docker.image_ref("v2")

    assert ref == "registry.example/logos/logos-workernode-vllm:v2"
    argv = runner.calls[0][0]
    assert argv[-3:] == ("config", "--images", "logos-workernode")
    assert "--format" not in argv


def test_an_unexpected_number_of_images_is_an_error(settings):
    docker, _ = docker_with(settings, ok("a:1\nb:2\n"))

    with pytest.raises(DockerError, match="expected one image"):
        docker.image_ref("v2")


def test_a_failing_compose_config_is_an_error(settings):
    docker, _ = docker_with(settings, failed("yaml: line 3: mapping values are not allowed"))

    with pytest.raises(DockerError, match="mapping values"):
        docker.image_ref("v2")


def test_a_container_is_read_from_docker_inspect(settings):
    docker, _ = docker_with(settings, ok(inspect_json(Health={"Status": "healthy"})))

    info = docker.container()

    assert info.id == "abc123"
    assert info.image_id == "sha256:img"
    assert info.image_ref.endswith(":latest")
    assert info.running
    assert info.health == "healthy"


def test_a_container_without_a_health_check_has_no_health(settings):
    docker, _ = docker_with(settings, ok(inspect_json()))

    assert docker.container().health is None


def test_a_missing_container_is_none(settings):
    docker, _ = docker_with(settings, failed("Error: No such container: logos-workernode"))

    assert docker.container() is None


def test_other_inspect_failures_are_errors(settings):
    docker, _ = docker_with(settings, failed("Cannot connect to the Docker daemon"))

    with pytest.raises(DockerError, match="Cannot connect"):
        docker.container()


def test_garbage_from_inspect_is_an_error(settings):
    docker, _ = docker_with(settings, ok("not json"))

    with pytest.raises(DockerError, match="unexpected output"):
        docker.container()


def test_an_image_id_is_read_and_a_missing_image_is_none(settings):
    docker, _ = docker_with(settings, ok("sha256:abc\n"), failed("Error: No such image: x"))

    assert docker.image_id("x:1") == "sha256:abc"
    assert docker.image_id("x:2") is None


def test_a_failing_tag_is_an_error(settings):
    docker, _ = docker_with(settings, failed("Error response from daemon: No such image: sha256:gone"))

    with pytest.raises(DockerError, match="docker tag failed"):
        docker.tag("sha256:gone", "x:previous")


def test_removing_an_image_that_is_in_use_is_not_an_error(settings):
    docker, _ = docker_with(settings, failed("image is being used by running container"))

    assert docker.remove_image("sha256:abc") is False


def test_the_log_combines_both_streams(settings):
    docker, runner = docker_with(settings, CommandResult(("x",), 0, stdout="out line\n", stderr="err line\n"))

    assert docker.container_logs(10) == "out line\nerr line"
    assert runner.calls[0][0] == ("docker", "logs", "--tail", "10", "logos-workernode")


def test_the_versions_line_never_raises(settings):
    docker, _ = docker_with(settings, failed("Cannot connect to the Docker daemon"), ok("2.40.3\n"))

    line = docker.versions()

    assert "engine unavailable" in line
    assert "compose 2.40.3" in line


def test_the_registry_login_is_described_without_its_secrets(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"auths": {"harbor.example": {"auth": "c2VjcmV0"}}}), encoding="utf-8")

    text = describe_registry_login(config)

    assert "1 registry login(s)" in text
    assert "c2VjcmV0" not in text
    assert "harbor.example" not in text


def test_a_credential_helper_is_pointed_out(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"credsStore": "desktop"}), encoding="utf-8")

    assert "credential helper" in describe_registry_login(config)


def test_a_missing_login_file_is_reported(tmp_path):
    assert "no Docker login file" in describe_registry_login(tmp_path / "missing.json")
