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
ARG VLLM_PIP_SPEC=vllm
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
         # 1. Install vLLM (pins torch to its required version from PyPI)
         pip install --no-cache-dir --prefix=/install --ignore-installed $VLLM_PIP_SPEC; \
         site_pkgs="$(python3 -c 'import sysconfig; print(sysconfig.get_path("purelib", vars={"base":"/install","platbase":"/install"}))')"; \
         # 2. Reinstall torch+vision+audio with CUDA wheels matching vLLM's pinned version.
         #    Extract the exact versions vLLM installed so the ABI stays consistent.
         PYTHONPATH="$site_pkgs" python3 -c "import importlib.metadata as m; print(m.version('torch'))"  > /tmp/_torch_ver; \
         PYTHONPATH="$site_pkgs" python3 -c "import importlib.metadata as m; print(m.version('torchvision'))" > /tmp/_tv_ver; \
         PYTHONPATH="$site_pkgs" python3 -c "import importlib.metadata as m; print(m.version('torchaudio'))"  > /tmp/_ta_ver; \
         pip install --no-cache-dir --prefix=/install \
             --ignore-installed --force-reinstall --no-deps \
             --extra-index-url https://download.pytorch.org/whl/cu128 \
             "torch==$(cat /tmp/_torch_ver)" \
             "torchvision==$(cat /tmp/_tv_ver)" \
             "torchaudio==$(cat /tmp/_ta_ver)"; \
         # 3. Optional: override NCCL version
         if [ -n "$NCCL_PIP_SPEC" ]; then \
           rm -rf "$site_pkgs/nvidia/nccl" "$site_pkgs"/nvidia_nccl_cu12-*.dist-info; \
           pip install --no-cache-dir --prefix=/install --ignore-installed --force-reinstall --no-deps "$NCCL_PIP_SPEC"; \
           expected_nccl="${NCCL_PIP_SPEC#nvidia-nccl-cu12==}"; \
           if [ "$expected_nccl" != "$NCCL_PIP_SPEC" ]; then \
             PYTHONPATH="$site_pkgs" python3 -c "import importlib.metadata as m; actual = m.version('nvidia-nccl-cu12'); assert actual == '$expected_nccl', f'expected $expected_nccl, got {actual}'"; \
           fi; \
         fi; \
         # 4. FlashInfer
         pip install --no-cache-dir --prefix=/install flashinfer-python; \
         # 5. Verify torch ABI consistency
         PYTHONPATH="$site_pkgs" python3 -c "\
import importlib.metadata as m; \
tv = m.version('torch'); \
import pathlib, subprocess; \
so = str(pathlib.Path('$site_pkgs') / 'vllm' / '_C.abi3.so'); \
r = subprocess.run(['ldd', so], capture_output=True, text=True); \
nf = [l.strip() for l in r.stdout.splitlines() if 'not found' in l]; \
print(f'torch={tv}, unresolved libs={len(nf)}'); \
[print(f'  {l}') for l in nf]; \
"; \
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
# Stage 2b: CUDA toolkit exporter
# GPU builds (BASE_IMAGE=nvidia/cuda:*-devel): nvcc, headers, and device libs
# are already present. The mkdir just ensures the paths always exist.
# CPU builds (BASE_IMAGE=python:3.12-slim): creates empty dirs so the COPY
# instructions in Stage 3 become safe no-ops instead of errors.
# ---------------------------------------------------------------------------
FROM ${BASE_IMAGE} AS cuda-exporter
RUN mkdir -p /usr/local/cuda/bin /usr/local/cuda/include /usr/local/cuda/nvvm/libdevice

# ---------------------------------------------------------------------------
# Stage 3: Runtime image
#   CPU build  (BASE_IMAGE=python:3.12-slim):    lightweight, no CUDA overhead
#   GPU build  (BASE_IMAGE=nvidia/cuda:...):      CUDA runtime only; nvcc and
#              headers are copied from cuda-exporter below, keeping the image
#              self-contained without needing the full -devel base (~2 GB saved).
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
# Bake nvcc + CUDA headers from the devel base so GPU lanes can JIT-compile
# kernels (FlashInfer, Triton) without a host /usr/local/cuda mount or the full
# -devel base image. No-op for CPU builds (cuda-exporter dirs are empty there).
COPY --from=cuda-exporter /usr/local/cuda/bin/            /usr/local/cuda/bin/
COPY --from=cuda-exporter /usr/local/cuda/include/        /usr/local/cuda/include/
COPY --from=cuda-exporter /usr/local/cuda/nvvm/libdevice/ /usr/local/cuda/nvvm/libdevice/
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

# CUDA system libs and PyTorch native libs (libc10, libtorch, etc.)
# vLLM's _C extension links against torch libs that must be on LD_LIBRARY_PATH.
RUN TORCH_LIB="$(python3 -c 'import pathlib, sysconfig; p = pathlib.Path(sysconfig.get_path("purelib")) / "torch" / "lib"; print(p) if p.is_dir() else print("")' 2>/dev/null)" \
    && echo "TORCH_LIB=${TORCH_LIB}" \
    && if [ -n "$TORCH_LIB" ]; then echo "$TORCH_LIB" > /etc/ld.so.conf.d/torch.conf && ldconfig; fi
ENV LD_LIBRARY_PATH=/usr/local/cuda/lib64:/usr/local/cuda/extras/CUPTI/lib64:${LD_LIBRARY_PATH}

# NCCL — 2× Quadro RTX 5000 are PCIe-connected (no NVLink bridge on Turing RTX 5000)
ENV NCCL_IB_DISABLE=1
ENV NCCL_DEBUG=WARN

EXPOSE ${WORKER_PORT:-80}

CMD ["python3", "-m", "logos_worker_node.main"]
