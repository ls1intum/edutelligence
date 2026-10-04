# Simulated worker node: the real logos_worker_node, fake hardware underneath.
#
# The production image is a CUDA base with vLLM compiled in — several GB, and it
# needs an NVIDIA container runtime to start. This image swaps that bottom layer
# for the GPU simulator: same worker code, same config handling, same bridge
# protocol, but `nvidia-smi` and `vllm` on PATH are the shims from
# harness/gpusim/bin.
#
# That keeps the whole inter-node tier runnable on an ordinary CI runner, and
# keeps the thing being tested honest — no worker module is stubbed or patched.
#
# Build context is the `logos/` directory:
#   docker build -f e2e/harness/nodesim/Dockerfile logos/

FROM python:3.13-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# procps/psmisc: the worker walks the process tree (pgrep) when accounting for
# host RAM across vLLM TP workers, and the watchdog's diagnostics dump shells
# out for system state. Leaving them out would test failure paths nobody asked
# about.
RUN apt-get update \
  && apt-get install -y --no-install-recommends procps psmisc curl \
  && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /usr/local/bin/uv

COPY logos-workernode/requirements.txt /tmp/requirements.txt
# vllm and its CUDA stack are deliberately excluded: the simulator provides the
# `vllm` binary, and installing the real one would pull ~5 GB of wheels that no
# simulated lane ever loads.
RUN grep -viE '^(vllm|torch|nvidia-|flashinfer)' /tmp/requirements.txt > /tmp/requirements.sim.txt \
 && uv pip install --system -r /tmp/requirements.sim.txt

COPY logos-workernode/logos_worker_node/ /app/logos_worker_node/
COPY e2e/harness/ /app/harness/

# The shims resolve their own imports relative to this layout, so `harness` must
# sit where `parents[3]` from harness/gpusim/bin/<tool> lands.
ENV PATH="/app/harness/gpusim/bin:${PATH}" \
    PYTHONPATH=/app \
    LOGOS_GPUSIM_STATE=/app/state/gpusim.json \
    LOGOS_GPUSIM_VLLM_SCRIPT=/app/state/vllm_script.json \
    LOGOS_WORKER_NODE_CONFIG=/app/config.yml \
    LOGOS_STATE_DIR=/app/data

COPY e2e/harness/nodesim/entrypoint.py /app/entrypoint.py

EXPOSE 80
CMD ["python", "/app/entrypoint.py"]
