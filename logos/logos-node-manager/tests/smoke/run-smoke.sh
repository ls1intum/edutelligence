#!/usr/bin/env bash
# Checks the node manager against a real Docker engine, without a GPU.
#
# It starts a local registry, builds a dummy worker in four flavors (v1, v2, v3 and a broken one), runs the real manager
# image next to a dummy worker in a throw-away compose project, and asks the manager for deployments. After each one it
# counts the dummy worker images on the host, to see that none is left that no longer has a purpose. Everything it
# creates is named nm-smoke... and is removed at the end. Set KEEP=1 to keep it for a look.
#
# Needs a running Docker engine with the Compose plugin, and network access for the base images.
#   logos/logos-node-manager/tests/smoke/run-smoke.sh
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPONENT="$(cd "$HERE/../.." && pwd)"

PORT="${SMOKE_REGISTRY_PORT:-5001}"
REGISTRY="localhost:${PORT}"
WORKER=nm-smoke-worker
MANAGER=nm-smoke-manager
REGISTRY_CONTAINER=nm-smoke-registry
MANAGER_IMAGE=nm-smoke-manager:local

# The project directory is mounted into the manager at the same path, so the Docker engine must be able to share it, and
# it should not contain spaces. The path of this repository does.
WORK="${SMOKE_DIR:-/tmp/nm-smoke}"
case "$(basename "$WORK")" in
  nm-smoke*) ;;
  *) echo "error: SMOKE_DIR must name a directory that starts with nm-smoke, because it is deleted at the end" >&2; exit 2 ;;
esac

failures=0
log() { printf '\n== %s\n' "$*"; }
pass() { printf '   ok: %s\n' "$*"; }
fail() { printf '   FAILED: %s\n' "$*"; failures=$((failures + 1)); }
die() { printf 'error: %s\n' "$*" >&2; exit 2; }

expect_equal() { # description, expected, actual
  if [ "$2" = "$3" ]; then pass "$1"; else fail "$1 (expected '$2', got '$3')"; fi
}

nm() { docker exec "$MANAGER" node-manager "$@"; }
worker_image() { docker inspect --format '{{.Config.Image}}' "$WORKER" 2>/dev/null; }
worker_healthy() { [ "$(docker inspect --format '{{.State.Health.Status}}' "$WORKER" 2>/dev/null)" = healthy ]; }
phase_is() { nm status "$1" --json 2>/dev/null | grep -q "\"phase\": \"$2\""; }
image_exists() { docker image inspect "$1" >/dev/null 2>&1; }

# The dummy worker images carry the label nm-smoke, so they can be counted whether they have a name or not. An image
# with several names is listed once per name.
smoke_images() { docker images -q --filter label=nm-smoke | sort -u | wc -l | tr -d ' '; }
# The manager removes old images right after it has saved the result, so the result can arrive a moment before.
clean_up_finished() { docker logs "$MANAGER" 2>&1 | grep -q "Deployment $1: clean-up finished"; }
expect_images() { # deployment id, number of dummy worker images on the host, description
  if wait_for 60 clean_up_finished "$1"; then
    expect_equal "$3" "$2" "$(smoke_images)"
  else
    fail "$3 (the manager did not finish the clean-up of $1)"
  fi
}

wait_for() { # seconds, command...
  local limit=$1
  shift
  for _ in $(seq 1 "$limit"); do
    if "$@" >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  return 1
}

remove_leftovers() {
  docker rm -f "$WORKER" "$MANAGER" "$REGISTRY_CONTAINER" >/dev/null 2>&1
  docker rmi -f "$MANAGER_IMAGE" "$REGISTRY/dummy-worker:v1" "$REGISTRY/dummy-worker:v2" "$REGISTRY/dummy-worker:v3" \
    "$REGISTRY/dummy-worker:broken" "$REGISTRY/dummy-worker:previous" >/dev/null 2>&1
  # Images that lost their name, which a run that found a leak leaves behind.
  docker images -q --filter label=nm-smoke | sort -u | xargs docker rmi -f >/dev/null 2>&1
  docker network rm nm-smoke_default >/dev/null 2>&1
}

cleanup() {
  if [ "${KEEP:-0}" = "1" ]; then
    echo "KEEP=1: leaving $WORK and the nm-smoke containers in place"
    return
  fi
  remove_leftovers
  rm -rf "$WORK"
}
trap cleanup EXIT

docker info >/dev/null 2>&1 || die "no Docker engine is reachable"
docker compose version >/dev/null 2>&1 || die "the Docker Compose plugin is missing"

remove_leftovers
rm -rf "$WORK"
mkdir -p "$WORK/node-manager"
# Resolve symbolic links (/tmp is one on macOS), so that the path is the same on the host and in the manager.
WORK="$(cd "$WORK" && pwd -P)"

log "Starting a local registry on $REGISTRY"
docker run -d --name "$REGISTRY_CONTAINER" -p "127.0.0.1:${PORT}:5000" registry:2 >/dev/null ||
  die "could not start the registry (is port $PORT free?)"
wait_for 30 curl -fsS "http://$REGISTRY/v2/" || die "the registry does not answer"

log "Building and pushing the dummy worker (v1, v2, v3, broken)"
build_worker() { # tag, mode
  docker build -q --build-arg "VERSION=$1" --build-arg "MODE=$2" -t "$REGISTRY/dummy-worker:$1" \
    "$HERE/dummy-worker" >/dev/null || die "the build of $1 failed"
  docker push -q "$REGISTRY/dummy-worker:$1" >/dev/null || die "the push of $1 failed"
}
build_worker v1 good
build_worker v2 good
build_worker v3 good
build_worker broken broken
# Remove the local copies, so that the deployments really download these images.
docker rmi "$REGISTRY/dummy-worker:v2" "$REGISTRY/dummy-worker:v3" "$REGISTRY/dummy-worker:broken" >/dev/null

log "Building the node manager image"
docker build -q -t "$MANAGER_IMAGE" "$COMPONENT" >/dev/null || die "the build of the manager image failed"

cp "$HERE/compose.yml" "$WORK/docker-compose.yml"
echo '{}' >"$WORK/docker-config.json"
cat >"$WORK/.env" <<EOF
SMOKE_DIR=$WORK
SMOKE_REGISTRY=$REGISTRY
IMAGE_TAG=v1
COMPOSE_PROFILES=node-manager
EOF
compose() { docker compose -p nm-smoke -f "$WORK/docker-compose.yml" --env-file "$WORK/.env" "$@"; }

log "Starting the dummy worker (v1) and the manager"
compose up -d worker node-manager || die "docker compose up failed"
wait_for 60 worker_healthy || die "the dummy worker did not become healthy"
wait_for 60 nm ping || die "the manager did not start"
expect_equal "the worker starts on v1" "$REGISTRY/dummy-worker:v1" "$(worker_image)"

log "1. A healthy release replaces the container"
nm deploy --id t1 --tag v2 --wait --timeout 240
expect_equal "the deployment exits with 0" 0 "$?"
expect_equal "the worker runs v2" "$REGISTRY/dummy-worker:v2" "$(worker_image)"
if docker image inspect "$REGISTRY/dummy-worker:previous" >/dev/null 2>&1; then
  pass "the previous version is kept under its own name"
else
  fail "the previous version is not kept under its own name"
fi
expect_images t1 2 "the host keeps the running image and the previous one"

log "2. A broken release is rolled back"
nm deploy --id t2 --tag broken --wait --timeout 240
expect_equal "the deployment exits with 10 (rolled back)" 10 "$?"
expect_equal "the worker runs v2 again" "$REGISTRY/dummy-worker:v2" "$(worker_image)"
if nm status t2 --json | grep -q "broken build"; then
  pass "the log of the broken container is saved in the record"
else
  fail "the log of the broken container is not in the record"
fi
expect_images t2 1 "only the running image is left on the host"
if image_exists "$REGISTRY/dummy-worker:broken"; then
  fail "the image of the failed release is still on the host"
else
  pass "the image of the failed release is removed"
fi
if image_exists "$REGISTRY/dummy-worker:v1"; then
  fail "the image from two versions back is still on the host"
else
  pass "the image from two versions back is removed"
fi

log "3. A tag that does not exist leaves the container alone"
nm deploy --id t3 --tag nope --wait --timeout 240
expect_equal "the deployment exits with 11 (failed)" 11 "$?"
expect_equal "the worker still runs v2" "$REGISTRY/dummy-worker:v2" "$(worker_image)"
if nm status t3 --json | grep -q '"failure": "pull_failed"'; then
  pass "the failure is reported as pull_failed"
else
  fail "the failure is not reported as pull_failed"
fi
expect_images t3 1 "the host is left as it was"

log "4. A request for the image that runs already changes nothing"
nm deploy --id t4 --tag v2 --wait --timeout 240
expect_equal "the deployment exits with 0" 0 "$?"
if nm status t4 --json | grep -q '"outcome": "unchanged"'; then
  pass "the outcome is unchanged"
else
  fail "the outcome is not unchanged"
fi
expect_images t4 1 "the host is left as it was"

log "5. The manager restarts in the middle of a deployment"
nm deploy --id t5 --tag v1 >/dev/null
if wait_for 90 phase_is t5 verifying; then
  docker restart "$MANAGER" >/dev/null
  wait_for 60 nm ping || die "the manager did not come back"
  nm wait t5 --timeout 240
  expect_equal "the deployment exits with 0 after the restart" 0 "$?"
  expect_equal "the worker runs v1" "$REGISTRY/dummy-worker:v1" "$(worker_image)"
  # The log of a container survives a restart, so it shows that the manager took the deployment up again where the
  # record said it was, and did not just happen to finish it.
  if docker logs "$MANAGER" 2>&1 | grep -q "Processing deployment t5 (tag v1, phase verifying)"; then
    pass "the manager continued the deployment from the recorded phase"
  else
    fail "the manager did not continue the deployment from the recorded phase"
  fi
  expect_images t5 2 "the host keeps the running image and the previous one"
else
  fail "the deployment never reached the verification phase"
fi

log "6. A later success removes the image from two versions back"
# The name previous points to v2 now, and v1 runs. The new release moves the name to v1, and v2 is two versions old.
nm deploy --id t6 --tag v3 --wait --timeout 240
expect_equal "the deployment exits with 0" 0 "$?"
expect_equal "the worker runs v3" "$REGISTRY/dummy-worker:v3" "$(worker_image)"
expect_images t6 2 "the host keeps the running image and the previous one"
if image_exists "$REGISTRY/dummy-worker:v2"; then
  fail "the image from two versions back is still on the host"
else
  pass "the image from two versions back is removed"
fi

if [ "$failures" -eq 0 ]; then
  log "All checks passed"
else
  log "$failures check(s) failed"
  echo "--- end of the manager log ---"
  docker logs --tail 80 "$MANAGER" 2>&1
fi
[ "$failures" -eq 0 ]
