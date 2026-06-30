#!/usr/bin/env bash
#
# build-and-push-anon.sh — Build the stack as anonymized images and push them
# to Docker Hub (https://app.docker.com/accounts/icse27review).
#
# Repository names are neutral (orchestrator / webservice / ui / db / worker-vllm)
# and contain no project name, so the registry listing stays anonymous for
# double-blind review.
#
# NOTE: this anonymizes the *published repository names and tags*. The image
# layers still contain the original source tree (file paths, package names), so
# a reviewer who unpacks a layer can still read it. Renaming the source is out
# of scope for this script.
#
# Usage:
#   ./scripts/build-and-push-anon.sh [service ...]
#
#   # all services (skips the heavy GPU worker unless asked):
#   ./scripts/build-and-push-anon.sh
#
#   # a subset:
#   ./scripts/build-and-push-anon.sh orchestrator ui
#
#   # include the CUDA/vLLM worker image (large, slow to build):
#   ./scripts/build-and-push-anon.sh worker-vllm
#
# Environment:
#   NAMESPACE   Docker Hub namespace            (default: icse27review)
#   TAG         Image tag                       (default: latest)
#   PLATFORM    Target platform                 (default: linux/amd64)
#   PUSH        Push after build (0 to skip)    (default: 1)
#   DOCKER_LOGIN  Run `docker login` first (1)  (default: 0; assumes already logged in)
#
set -euo pipefail

NAMESPACE="${NAMESPACE:-icse27review}"
TAG="${TAG:-latest}"
PLATFORM="${PLATFORM:-linux/amd64}"
PUSH="${PUSH:-1}"
DOCKER_LOGIN="${DOCKER_LOGIN:-0}"

# Resolve paths: this script lives in <repo>/logos/scripts.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGOS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"   # <repo>/logos
REPO_ROOT="$(cd "${LOGOS_DIR}/.." && pwd)"    # <repo> (edutelligence root)

# Service registry. Each entry:
#   <name>|<anon-image>|<context-dir>|<dockerfile>|<extra build-args, ';'-separated>
# Paths are relative to REPO_ROOT to keep the orchestrator's repo-root context
# working (its Dockerfile COPYs both logos/ and shared/).
SERVICES=(
  "orchestrator|orchestrator|.|logos/logos-orchestrator/Dockerfile|"
  "webservice|webservice|logos/logos-webservice|logos/logos-webservice/Dockerfile|"
  "ui|ui|logos/logos-ui|logos/logos-ui/Dockerfile|"
  "db|db|logos/db|logos/db/Dockerfile|"
  "worker-vllm|worker-vllm|logos/logos-workernode|logos/logos-workernode/Dockerfile|BASE_IMAGE=nvidia/cuda:13.1.1-cudnn-devel-ubuntu24.04;RUNTIME_IMAGE=nvidia/cuda:13.1.1-cudnn-runtime-ubuntu24.04;INSTALL_VLLM=1;INSTALL_OLLAMA=0"
)

# Services built by default when no arguments are given.
# Note: the worker-vllm image is a multi-gigabyte CUDA/vLLM build and is slow.
DEFAULT_SERVICES=(orchestrator db worker-vllm)

lookup() {
  local want="$1" entry
  for entry in "${SERVICES[@]}"; do
    [[ "${entry%%|*}" == "$want" ]] && { echo "$entry"; return 0; }
  done
  return 1
}

# Decide which services to build.
declare -a TARGETS
if [[ $# -gt 0 ]]; then
  TARGETS=("$@")
else
  TARGETS=("${DEFAULT_SERVICES[@]}")
fi

# Validate up front.
for name in "${TARGETS[@]}"; do
  if ! lookup "$name" >/dev/null; then
    echo "error: unknown service '$name'" >&2
    echo "known services: orchestrator webservice ui db worker-vllm" >&2
    exit 1
  fi
done

if [[ "$DOCKER_LOGIN" == "1" ]]; then
  echo ">> docker login (namespace: ${NAMESPACE})"
  docker login
fi

echo ">> namespace=${NAMESPACE} tag=${TAG} platform=${PLATFORM} push=${PUSH}"
echo ">> building: ${TARGETS[*]}"
echo

for name in "${TARGETS[@]}"; do
  entry="$(lookup "$name")"
  IFS='|' read -r _ image context dockerfile buildargs <<<"$entry"

  ref="${NAMESPACE}/${image}:${TAG}"

  declare -a args=(
    build
    --platform "$PLATFORM"
    -t "$ref"
    -f "${REPO_ROOT}/${dockerfile}"
  )

  if [[ -n "$buildargs" ]]; then
    IFS=';' read -ra ba <<<"$buildargs"
    for kv in "${ba[@]}"; do
      args+=(--build-arg "$kv")
    done
  fi

  args+=("${REPO_ROOT}/${context}")

  echo ">> [${name}] building ${ref}"
  docker "${args[@]}"

  if [[ "$PUSH" == "1" ]]; then
    echo ">> [${name}] pushing ${ref}"
    docker push "$ref"
  fi
  echo
done

echo ">> done."
