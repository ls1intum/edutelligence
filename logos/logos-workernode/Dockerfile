# =============================================================================
# Logos Worker Node
#
# CPU / local build  (default):  BASE_IMAGE=python:3.12-slim, INSTALL_VLLM=0
# GPU build (--gpu flag):        BASE_IMAGE=nvidia/cuda:13.2.0-cudnn-devel-ubuntu24.04
#                                RUNTIME_IMAGE=nvidia/cuda:13.2.0-cudnn-runtime-ubuntu24.04
#                                INSTALL_VLLM=1
#
# The builder stage needs -devel (compilers/headers) but the runtime stage only
# needs -runtime, saving ~2 GB in the final image.
#
# Host (GPU): driver 590.48.01 | CUDA 13.1 | 2× Quadro RTX 5000 (16 GB each)
# vLLM/PyTorch wheels: cu128 (newest on PyPI under CUDA 13.1 driver).
# =============================================================================

ARG BASE_IMAGE=python:3.12-slim
ARG RUNTIME_IMAGE=${BASE_IMAGE}
ARG INSTALL_VLLM=0
ARG VLLM_PIP_SPEC=vllm --extra-index-url https://download.pytorch.org/whl/cu128
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
# Stage 2: Build — install Python deps
#   CPU build  (BASE_IMAGE=python:3.12-slim):    Python already present, skip OS setup
#   GPU build  (BASE_IMAGE=nvidia/cuda:...):      Install Python 3.13 from deadsnakes PPA
# ---------------------------------------------------------------------------
FROM ${BASE_IMAGE} AS builder
ARG INSTALL_VLLM
ARG VLLM_PIP_SPEC
ARG NCCL_PIP_SPEC

# Install Python 3.13 only when not already available (GPU/Ubuntu base).
# python:*-slim images already have python3 + pip.
RUN if ! command -v python3 >/dev/null 2>&1; then \
        apt-get update \
        && apt-get install -y --no-install-recommends software-properties-common ca-certificates gpg-agent \
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

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt \
    && if [ "$INSTALL_VLLM" = "1" ]; then \
         pip install --no-cache-dir --prefix=/install --ignore-installed $VLLM_PIP_SPEC; \
         site_pkgs="$(python3 -c 'import sysconfig; print(sysconfig.get_path("purelib", vars={"base":"/install","platbase":"/install"}))')"; \
         if [ -n "$NCCL_PIP_SPEC" ]; then \
           rm -rf "$site_pkgs/nvidia/nccl" "$site_pkgs"/nvidia_nccl_cu12-*.dist-info; \
           pip install --no-cache-dir --prefix=/install --ignore-installed --force-reinstall --no-deps "$NCCL_PIP_SPEC"; \
           expected_nccl="${NCCL_PIP_SPEC#nvidia-nccl-cu12==}"; \
           if [ "$expected_nccl" != "$NCCL_PIP_SPEC" ]; then \
             PYTHONPATH="$site_pkgs" python3 -c "import importlib.metadata as m; actual = m.version('nvidia-nccl-cu12'); assert actual == '$expected_nccl', f'expected $expected_nccl, got {actual}'"; \
           fi; \
         fi; \
         pip install --no-cache-dir --prefix=/install flashinfer-python; \
       fi
# Normalize: pip --prefix layout varies across distros (lib/ vs local/lib/,
# site-packages vs dist-packages).  Move everything into a flat /packages dir
# so the runtime COPY is deterministic.
RUN site_dir="$(python3 -c 'import sysconfig; print(sysconfig.get_path("purelib", vars={"base":"/install","platbase":"/install"}))')"; \
    mkdir -p /packages && cp -a "$site_dir"/. /packages/
# Collect console_scripts (e.g. vllm) installed under --prefix into /scripts.
RUN mkdir -p /scripts \
    && for d in /install/bin /install/local/bin; do \
         [ -d "$d" ] && cp -a "$d"/. /scripts/; \
       done; true

# ---------------------------------------------------------------------------
# Stage 3: Runtime image
#   CPU build  (BASE_IMAGE=python:3.12-slim):    lightweight, no CUDA overhead
#   GPU build  (BASE_IMAGE=nvidia/cuda:...):      CUDA runtime only (no compilers)
#
# RUNTIME_IMAGE defaults to BASE_IMAGE, but for GPU builds should be overridden
# to the -runtime variant to save ~2 GB (no dev headers/compilers/static libs).
# ---------------------------------------------------------------------------
ARG RUNTIME_IMAGE
FROM ${RUNTIME_IMAGE}
ARG INSTALL_VLLM
ARG INSTALL_OLLAMA

# Install Python 3.13 only on GPU/Ubuntu base (same logic as builder stage).
# When INSTALL_VLLM=1, also install a C compiler for Triton JIT kernel compilation.
RUN if ! command -v python3 >/dev/null 2>&1; then \
        apt-get update \
        && apt-get install -y --no-install-recommends software-properties-common ca-certificates gpg-agent \
        && add-apt-repository -y ppa:deadsnakes/ppa \
        && apt-get update \
        && apt-get install -y --no-install-recommends \
            python3.13 python3.13-venv \
            curl libnuma1 \
        && if [ "$INSTALL_VLLM" = "1" ]; then \
            apt-get install -y --no-install-recommends gcc; \
           fi \
        && rm -rf /var/lib/apt/lists/* \
        && ln -sf /usr/bin/python3.13 /usr/bin/python3 \
        && ln -sf /usr/bin/python3.13 /usr/bin/python \
        && curl -sS https://bootstrap.pypa.io/get-pip.py | python3; \
    fi

WORKDIR /app
# Copy packages into whichever directory this Python's import system expects.
RUN mkdir -p "$(python3 -c 'import sysconfig; print(sysconfig.get_path("purelib"))')"
COPY --from=builder /packages/ /tmp/packages/
RUN cp -a /tmp/packages/. "$(python3 -c 'import sysconfig; print(sysconfig.get_path("purelib"))')/" \
    && rm -rf /tmp/packages
COPY --from=builder /scripts/ /usr/local/bin/
COPY --from=ollama-builder /ollama-root/ /
COPY logos_worker_node/ /app/logos_worker_node/
RUN mkdir -p /app/certs /app/data

# ---------------------------------------------------------------------------
# Runtime environment
# ---------------------------------------------------------------------------
ENV PYTHONUNBUFFERED=1
ENV LOGOS_WORKER_NODE_HAS_VLLM=${INSTALL_VLLM}
ENV LOGOS_WORKER_NODE_HAS_OLLAMA=${INSTALL_OLLAMA}
ENV LOGOS_WORKER_NODE_CONFIG=/app/config.yml
ENV LOGOS_STATE_DIR=/app/data

# CUDA system libs — only relevant on GPU builds, harmless on CPU
ENV LD_LIBRARY_PATH=/usr/local/cuda/lib64:/usr/local/cuda/extras/CUPTI/lib64:${LD_LIBRARY_PATH}

# NCCL — 2× Quadro RTX 5000 are PCIe-connected (no NVLink bridge on Turing RTX 5000)
ENV NCCL_IB_DISABLE=1
ENV NCCL_DEBUG=WARN

EXPOSE ${WORKER_PORT:-80}

CMD ["python3", "-m", "logos_worker_node.main"]
