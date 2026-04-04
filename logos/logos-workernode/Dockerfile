# =============================================================================
# Logos Worker Node
#
# CPU / Ollama build (default):
#   BASE_IMAGE=python:3.12-slim   INSTALL_VLLM=0   INSTALL_OLLAMA=1
#
# GPU / vLLM build:
#   BASE_IMAGE=nvidia/cuda:13.1.1-cudnn-devel-ubuntu24.04
#   RUNTIME_IMAGE=nvidia/cuda:13.1.1-cudnn-runtime-ubuntu24.04
#   INSTALL_VLLM=1   INSTALL_OLLAMA=0
#
# Design notes
# ────────────
# • Both nvidia/cuda:*-devel and *-runtime images ship WITHOUT Python.
#   The builder installs Python 3.13 from the deadsnakes PPA.
#   python:*-slim images already have Python 3.12, so that block is skipped.
#
# • vLLM (via Triton) JIT-compiles CUDA kernels at runtime. This requires:
#     gcc            — C compiler for Triton's ctypes extension build
#     python3.13-dev — Python.h (Triton compiles a small C module at startup)
#     cuda-nvcc      — NVIDIA compiler for kernel PTX compilation
#     cuda-nvrtc     — CUDA runtime compilation library
#     libcublas      — cuBLAS (torch matmul kernels)
#     libnvvm        — provides libdevice.bc (PTX builtins used by nvcc)
#   This mirrors the official vLLM Dockerfile approach: accept that the runtime
#   image contains compiler tooling rather than pre-compiling everything.
#
# • libcuda.so.1 is NOT baked into the image.
#   The NVIDIA Container Runtime injects it at startup via the host driver
#   (typically /usr/local/cuda-<ver>/compat/ bind-mount). This ensures the
#   library always matches the host's driver version.
#
# Host (GPU): driver 590.48.01 | CUDA 13.1 | 2× Quadro RTX 5000 (16 GB each)
# vLLM/PyTorch wheels: cu128 (newest wheel index under CUDA 13.1 driver).
# =============================================================================

ARG BASE_IMAGE=python:3.12-slim
ARG RUNTIME_IMAGE=${BASE_IMAGE}
ARG INSTALL_VLLM=0
ARG VLLM_PIP_SPEC=vllm
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cu128
ARG NCCL_PIP_SPEC=
ARG INSTALL_OLLAMA=1

# ---------------------------------------------------------------------------
# Stage 1: Fetch latest Ollama release binary (no GPU libs needed here)
# ---------------------------------------------------------------------------
FROM debian:bookworm-slim AS ollama-builder
ARG INSTALL_OLLAMA

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl tar jq zstd \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /ollama-root/usr/local/bin /ollama-root/usr/local/lib \
    && if [ "$INSTALL_OLLAMA" = "1" ]; then \
        arch="$(dpkg --print-architecture)"; \
        case "$arch" in \
          amd64) ollama_arch="amd64" ;; \
          arm64) ollama_arch="arm64" ;; \
          *) echo "Unsupported architecture: $arch" >&2; exit 1 ;; \
        esac; \
        asset="ollama-linux-${ollama_arch}.tar.zst"; \
        release_json="$(curl -fsSL https://api.github.com/repos/ollama/ollama/releases/latest)"; \
        download_url="$(printf '%s' "$release_json" | jq -r --arg asset "$asset" '.assets[] | select(.name == $asset) | .browser_download_url' | head -n1)"; \
        if [ -z "$download_url" ] || [ "$download_url" = "null" ]; then \
          tag="$(printf '%s' "$release_json" | jq -r '.tag_name')"; \
          test -n "$tag" && test "$tag" != "null" || { echo "Could not resolve latest Ollama release tag" >&2; exit 1; }; \
          download_url="https://github.com/ollama/ollama/releases/download/${tag}/${asset}"; \
        fi; \
        curl -fsSL "$download_url" -o /tmp/ollama.tar.zst; \
        mkdir -p /tmp/ollama-extract; \
        tar --zstd -xf /tmp/ollama.tar.zst -C /tmp/ollama-extract; \
        if [ -x /tmp/ollama-extract/bin/ollama ]; then \
          cp /tmp/ollama-extract/bin/ollama /ollama-root/usr/local/bin/ollama; \
        elif [ -x /tmp/ollama-extract/ollama ]; then \
          cp /tmp/ollama-extract/ollama /ollama-root/usr/local/bin/ollama; \
        else \
          echo "Ollama binary not found in archive" >&2; exit 1; \
        fi; \
        if [ -d /tmp/ollama-extract/lib/ollama ]; then \
          cp -a /tmp/ollama-extract/lib/ollama /ollama-root/usr/local/lib/ollama; \
        fi; \
        chmod +x /ollama-root/usr/local/bin/ollama; \
      fi

# ---------------------------------------------------------------------------
# Stage 2: Build — install Python deps in a virtualenv
#
#   GPU build  (BASE_IMAGE=nvidia/cuda:*-devel-ubuntu24.04):
#     The devel image ships without Python. Install Python 3.13 from the
#     deadsnakes PPA, then build a python3.13 virtualenv with all packages.
#
#   CPU build  (BASE_IMAGE=python:3.12-slim):
#     Python 3.12 is already present. The `if ! command -v python3` block is
#     skipped. A python3.12 virtualenv is created.
# ---------------------------------------------------------------------------
FROM ${BASE_IMAGE} AS builder
ARG INSTALL_VLLM
ARG VLLM_PIP_SPEC
ARG TORCH_INDEX_URL
ARG NCCL_PIP_SPEC

# Install Python 3.13 only on base images that ship without Python (nvidia/cuda).
# python:*-slim images already provide python3 + pip — this block is skipped.
RUN if ! command -v python3 >/dev/null 2>&1; then \
        apt-get update \
        && apt-get install -y --no-install-recommends \
            software-properties-common ca-certificates gpg-agent \
        && add-apt-repository -y ppa:deadsnakes/ppa \
        && apt-get update \
        && apt-get install -y --no-install-recommends \
            python3.13 python3.13-dev python3.13-venv \
            build-essential curl \
        && rm -rf /var/lib/apt/lists/* \
        && ln -sf /usr/bin/python3.13 /usr/bin/python3 \
        && ln -sf /usr/bin/python3.13 /usr/bin/python \
        && curl -sS https://bootstrap.pypa.io/get-pip.py | python3; \
    fi \
    && python3 -m pip install --upgrade pip setuptools wheel

# Virtualenv keeps all packages self-contained and avoids system-level conflicts.
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ "$INSTALL_VLLM" = "1" ]; then \
         # 1. Install vLLM (pins torch to its required version from PyPI)
         pip install --no-cache-dir $VLLM_PIP_SPEC; \
         # 2. Reinstall torch from CUDA wheel index (same version, GPU-enabled)
         if [ -n "$TORCH_INDEX_URL" ]; then \
           torch_ver=$(python3 -c "import importlib.metadata as m; print(m.version('torch'))"); \
           echo "Reinstalling torch==${torch_ver} from ${TORCH_INDEX_URL}"; \
           pip install --no-cache-dir --force-reinstall --no-deps \
               --extra-index-url "$TORCH_INDEX_URL" \
               "torch==${torch_ver}"; \
         fi; \
         # 3. Optional: override NCCL version
         if [ -n "$NCCL_PIP_SPEC" ]; then \
           pip install --no-cache-dir --force-reinstall --no-deps "$NCCL_PIP_SPEC"; \
         fi; \
         # 4. FlashInfer (install AFTER torch so it picks up the correct version)
         pip install --no-cache-dir --no-deps flashinfer-python; \
       fi

# ---------------------------------------------------------------------------
# Stage 3: Runtime image
#
#   CPU build  (RUNTIME_IMAGE=python:3.12-slim):
#     Lightweight, no CUDA overhead. Ollama-only. Python 3.12 from base image.
#
#   GPU build  (RUNTIME_IMAGE=nvidia/cuda:*-runtime-ubuntu24.04):
#     CUDA runtime libraries only (~2 GB less than devel). No Python shipped.
#     Python 3.13 + dev headers are installed to match the builder's venv and
#     to satisfy Triton's runtime C compilation (see design notes at top).
#     The full CUDA toolchain (nvcc, nvrtc, cublas, nvvm) is installed via
#     versioned apt packages keyed off the CUDA_VERSION env var set by the
#     nvidia/cuda base image. This is the same approach used by the official
#     vLLM Dockerfile and avoids fragile COPY --from chains for CUDA libraries.
# ---------------------------------------------------------------------------
ARG RUNTIME_IMAGE
FROM ${RUNTIME_IMAGE}
ARG INSTALL_VLLM
ARG INSTALL_OLLAMA

# ── Python ────────────────────────────────────────────────────────────────────
# Install Python 3.13 when the runtime base has no Python at all (CUDA images),
# but only if INSTALL_VLLM=1 (the builder produced a python3.13 venv).
# CPU builds (python:3.12-slim, INSTALL_VLLM=0) already have python3.12 and
# the builder venv uses python3.12 — no install needed.
RUN if ! command -v python3.13 >/dev/null 2>&1 \
      && { [ "$INSTALL_VLLM" = "1" ] || ! command -v python3 >/dev/null 2>&1; }; then \
        apt-get update \
        && apt-get install -y --no-install-recommends \
            software-properties-common ca-certificates gpg-agent \
        && add-apt-repository -y ppa:deadsnakes/ppa \
        && apt-get update \
        && apt-get install -y --no-install-recommends \
            python3.13 python3.13-dev python3.13-venv curl libnuma1 \
        && rm -rf /var/lib/apt/lists/* \
        && ln -sf /usr/bin/python3.13 /usr/bin/python3 \
        && ln -sf /usr/bin/python3.13 /usr/bin/python \
        && curl -sS https://bootstrap.pypa.io/get-pip.py | python3; \
    fi

# ── CUDA toolchain for Triton / vLLM JIT compilation ─────────────────────────
# Installed via versioned apt packages (CUDA_VERSION is set by the base image).
# Package purposes:
#   cuda-nvcc   — NVIDIA compiler driver (nvcc) for kernel PTX generation
#   cuda-cudart — CUDA runtime (libcudart.so; needed by torch + vLLM)
#   cuda-nvrtc  — CUDA runtime compilation library (NVRTC)
#   libcublas   — cuBLAS (torch GEMM kernels)
#   libnvvm     — provides libdevice.bc, the PTX standard library used by nvcc
# gcc is the host C compiler Triton uses to compile its ctypes driver module.
# On non-CUDA base images (CPU builds) only gcc is installed.
RUN if [ "$INSTALL_VLLM" = "1" ] && [ -n "${CUDA_VERSION}" ]; then \
        CUDA_VER=$(echo "${CUDA_VERSION}" | cut -d. -f1,2 | tr '.' '-'); \
        apt-get update \
        && apt-get install -y --no-install-recommends \
            gcc \
            cuda-nvcc-${CUDA_VER} \
            cuda-cudart-${CUDA_VER} \
            cuda-nvrtc-${CUDA_VER} \
            libcublas-${CUDA_VER} \
            libnvvm-${CUDA_VER} \
        && rm -rf /var/lib/apt/lists/*; \
    elif [ "$INSTALL_VLLM" = "1" ]; then \
        apt-get update \
        && apt-get install -y --no-install-recommends gcc \
        && rm -rf /var/lib/apt/lists/*; \
    fi

WORKDIR /app
# Copy the entire virtualenv from the builder. The venv is self-contained —
# bin/, lib/, and include/ are all present with correct shebangs.
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:/usr/local/cuda/bin:$PATH"
RUN ldconfig
COPY --from=ollama-builder /ollama-root/ /
COPY logos_worker_node/ /app/logos_worker_node/
COPY tools/ /app/tools/
RUN mkdir -p /app/certs /app/data

# ---------------------------------------------------------------------------
# Runtime environment
# ---------------------------------------------------------------------------
ENV PYTHONUNBUFFERED=1
ENV LOGOS_WORKER_NODE_HAS_VLLM=${INSTALL_VLLM}
ENV LOGOS_WORKER_NODE_HAS_OLLAMA=${INSTALL_OLLAMA}
ENV LOGOS_WORKER_NODE_CONFIG=/app/config.yml
ENV LOGOS_STATE_DIR=/app/data

# CUDA library search path (GPU builds only — harmless on CPU).
# /usr/local/nvidia/lib64 — NVIDIA Container Runtime injects host driver libs
# /usr/local/cuda/lib64  — runtime libs from the cuda-* apt packages above
ENV LD_LIBRARY_PATH=/usr/local/nvidia/lib64:/usr/local/cuda/lib64:/usr/local/cuda/extras/CUPTI/lib64:${LD_LIBRARY_PATH}

# NCCL — 2× Quadro RTX 5000 are PCIe-connected (no NVLink/NVSwitch)
ENV NCCL_IB_DISABLE=1
ENV NCCL_DEBUG=WARN

EXPOSE ${WORKER_PORT:-80}

CMD ["python3", "-m", "logos_worker_node.main"]
