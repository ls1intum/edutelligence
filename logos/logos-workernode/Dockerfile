# =============================================================================
# Logos Worker Node
# Host: driver 590.48.01 | CUDA 13.1 | 2× Quadro RTX 5000 (16 GB each)
#
# vLLM/PyTorch wheels: cu128 (newest on PyPI under CUDA 13.1 driver).
# When cu131 PyTorch wheels ship: change VLLM_PIP_SPEC to cu131.
# =============================================================================

ARG CUDA_IMAGE=nvidia/cuda:13.1.0-cudnn-devel-ubuntu24.04
ARG INSTALL_VLLM=0
ARG VLLM_PIP_SPEC=vllm --extra-index-url https://download.pytorch.org/whl/cu128
ARG NCCL_PIP_SPEC=
ARG FLASHINFER_WHL_URL=https://flashinfer.ai/whl/cu128/torch2.10/
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
# Stage 2: Build — install Python deps against CUDA 13.1 system libs
# ---------------------------------------------------------------------------
FROM ${CUDA_IMAGE} AS builder
ARG INSTALL_VLLM
ARG VLLM_PIP_SPEC
ARG NCCL_PIP_SPEC
ARG FLASHINFER_WHL_URL

# Python 3.13 via deadsnakes PPA (Ubuntu 24.04 ships 3.12 by default)
RUN apt-get update \
    && apt-get install -y --no-install-recommends software-properties-common ca-certificates gpg-agent \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        python3.13 python3.13-dev python3.13-venv \
        build-essential curl \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3.13 /usr/bin/python3 \
    && ln -sf /usr/bin/python3.13 /usr/bin/python \
    && curl -sS https://bootstrap.pypa.io/get-pip.py | python3.13 \
    && python3.13 -m pip install --upgrade pip setuptools wheel

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt \
    && if [ "$INSTALL_VLLM" = "1" ]; then \
         pip install --no-cache-dir --prefix=/install $VLLM_PIP_SPEC; \
         site_pkgs="$(python -c 'import sysconfig; print(sysconfig.get_path("purelib", vars={"base":"/install","platbase":"/install"}))')"; \
         if [ -n "$NCCL_PIP_SPEC" ]; then \
           # Allow controlled NCCL trials without rewriting the rest of the vLLM stack.
           rm -rf "$site_pkgs/nvidia/nccl" "$site_pkgs"/nvidia_nccl_cu12-*.dist-info; \
           pip install --no-cache-dir --prefix=/install --ignore-installed --force-reinstall --no-deps "$NCCL_PIP_SPEC"; \
           expected_nccl="${NCCL_PIP_SPEC#nvidia-nccl-cu12==}"; \
           if [ "$expected_nccl" != "$NCCL_PIP_SPEC" ]; then \
             PYTHONPATH="$site_pkgs" python -c "import importlib.metadata as m; actual = m.version('nvidia-nccl-cu12'); assert actual == '$expected_nccl', f'expected $expected_nccl, got {actual}'"; \
           fi; \
         fi; \
         pip install --no-cache-dir --prefix=/install flashinfer-python \
             --index-url "${FLASHINFER_WHL_URL}"; \
       fi

# ---------------------------------------------------------------------------
# Stage 3: Runtime image — CUDA 13.1 + cuDNN + NCCL + Python 3.13
# ---------------------------------------------------------------------------
FROM ${CUDA_IMAGE}
ARG INSTALL_VLLM
ARG INSTALL_OLLAMA

RUN apt-get update \
    && apt-get install -y --no-install-recommends software-properties-common ca-certificates gpg-agent \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        python3.13 python3.13-venv \
        curl libnuma1 \
    && if [ "$INSTALL_VLLM" = "1" ]; then \
         apt-get install -y --no-install-recommends build-essential; \
       fi \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3.13 /usr/bin/python3 \
    && ln -sf /usr/bin/python3.13 /usr/bin/python \
    && curl -sS https://bootstrap.pypa.io/get-pip.py | python3.13

WORKDIR /app
COPY --from=builder /install /usr/local
COPY --from=ollama-builder /ollama-root/ /
COPY logos_worker_node/ /app/logos_worker_node/
RUN mkdir -p /app/certs

# ---------------------------------------------------------------------------
# Runtime environment
# ---------------------------------------------------------------------------
ENV PYTHONUNBUFFERED=1
ENV LOGOS_WORKER_NODE_HAS_VLLM=${INSTALL_VLLM}
ENV LOGOS_WORKER_NODE_HAS_OLLAMA=${INSTALL_OLLAMA}
ENV LOGOS_WORKER_NODE_CONFIG=/app/config.yml

# CUDA 13.1 system libs take priority over any bundled fallbacks in pip wheels
ENV LD_LIBRARY_PATH=/usr/local/cuda/lib64:/usr/local/cuda/extras/CUPTI/lib64:${LD_LIBRARY_PATH}

# NCCL — 2× Quadro RTX 5000 are PCIe-connected (no NVLink bridge on Turing RTX 5000)
# P2P over PCIe is enabled by default; suppress IB probing noise on non-IB hosts
ENV NCCL_IB_DISABLE=1
ENV NCCL_DEBUG=WARN

EXPOSE 8444

CMD ["python3.13", "-m", "logos_worker_node.main"]
