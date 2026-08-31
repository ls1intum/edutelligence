# =============================================================================
# Logos Worker Node
#
# Single build target — vLLM is always installed. There is no longer a
# CPU/Ollama-only variant (the Ollama engine was dropped). Build args:
#   BASE_IMAGE      (default ubuntu:24.04 — a base whose default Python is 3.12)
#   INSTALL_OLLAMA  (default 1 — set 0 to skip bundling the Ollama binary)
#
# Design notes
# ────────────
# • Single-stage Python install (no builder stage, no venv COPY).
#   The venv for a vLLM build is ~9 GB. A classic builder→runtime COPY keeps
#   two copies of it on the build host (builder layer + runtime layer), which
#   together with the old nvidia/cuda base images pushed peak build disk to
#   ~24 GB — past the ~14 GB GitHub-hosted runners guarantee. That was the
#   root cause of the intermittent "No space left on device" CI failures.
#   Everything we install is a binary wheel, so a build stage buys nothing:
#   the only compiler the image needs (gcc/g++ for Triton/FlashInfer runtime
#   JIT) must be in the final image anyway.
#
# • No nvidia/cuda base image and no apt CUDA packages.
#   Since vLLM ≥0.24 the PyPI wheel tree vendors a COMPLETE CUDA 13 toolkit:
#   <site-packages>/nvidia/cu13/ is a standard toolkit prefix with bin/nvcc,
#   bin/ptxas, nvvm/bin/cicc, nvvm/libdevice/libdevice.10.bc, include/
#   (cuda_runtime.h, cublas_v2.h, curand_kernel.h, nvrtc.h, …) and lib/ with
#   every math library — plus cudnn/nccl/nvshmem/cusparselt next to it.
#   That is the full header/compiler set FlashInfer's Blackwell SM 12.0
#   CUTLASS grouped-GEMM JIT pulls in (first triggered on deioma by
#   DeepSeek-OCR-2 MoE, see vllm-project/vllm#35501) — previously satisfied
#   by a wide set of apt cuda-*/lib*-dev packages that duplicated the wheels
#   ~1:1. CUDA_HOME points at the wheel prefix; the apt layer is gone.
#
#   Three small gaps in the wheel prefix are patched at build time:
#     lib64        — FlashInfer links with -L$CUDA_HOME/lib64; wheels ship
#                    lib/. A lib64→lib symlink fixes it.
#     lib*.so      — wheels ship only versioned SONAMEs (libcudart.so.13);
#                    `-lcudart` needs the unversioned dev symlink.
#     libcuda.so   — the JIT links -lcuda, normally resolved against the
#                    toolkit's driver stub. Wheels ship no stub, so we
#                    generate one from the wheel's own cuda.h: it exports
#                    every driver-API function (with the real versioned
#                    symbol names, e.g. cuMemAlloc_v2) under SONAME
#                    libcuda.so.1. An *empty* stub would not work — GCC
#                    links with --as-needed by default, so a library that
#                    resolves no symbols is dropped, leaving the JIT module
#                    with unresolved cu* symbols and no DT_NEEDED entry. At
#                    load time the DT_NEEDED libcuda.so.1 binds to the real
#                    driver injected by the NVIDIA Container Runtime.
#
# • libcuda.so.1 is NOT baked into the image.
#   The NVIDIA Container Runtime injects it at startup via the host driver.
#   This ensures the library always matches the host's driver version.
#   Because the base image is plain Ubuntu, NVIDIA_VISIBLE_DEVICES /
#   NVIDIA_DRIVER_CAPABILITIES are set here (nvidia/cuda bases used to).
#
# • uv instead of pip (pinned, bind-mounted so it never lands in a layer).
#   pip downloads all 4.3 GB of wheels before installing (peak = downloads +
#   installed tree); uv streams and hardlinks, keeping peak ≈ installed size,
#   and is much faster. Like the old image (which stripped __pycache__), no
#   bytecode is shipped; Python compiles lazily at first import.
#
# Host (GPU): driver 590.48.01 | CUDA 13.1 | 2× Quadro RTX 5000 (16 GB each)
# =============================================================================

ARG BASE_IMAGE=ubuntu:24.04
ARG VLLM_PIP_SPEC="vllm==v0.28.0"
# TORCH_INDEX_URL — leave empty (default) to use the PyPI torch that vLLM
# installs, which already includes CUDA support matching its nvidia-* deps.
# Only set this to override with a specific CUDA wheel index (e.g.
# https://download.pytorch.org/whl/cu128) for older vLLM versions whose
# PyPI torch was CPU-only.
ARG TORCH_INDEX_URL=
ARG NCCL_PIP_SPEC=
ARG INSTALL_OLLAMA=1

# ---------------------------------------------------------------------------
# uv — pinned to a specific version to mitigate supply-chain risk (update
# explicitly). Used via RUN --mount so the binary is never stored in a layer.
# ---------------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:0.12.5 AS uv

# ---------------------------------------------------------------------------
# Stage: Fetch latest Ollama release binary (no GPU libs needed here)
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
# Final image
#
#   Python 3.12 from the stock noble main repo (NOT the deadsnakes PPA —
#   GH Actions runners intermittently can't reach ppa.launchpadcontent.net,
#   which used to flake-fail builds; 3.12 is the default Ubuntu 24.04
#   Python and fully supported by vLLM). All CUDA libraries, compilers and
#   headers come from vLLM's pip dependency tree (see design notes above).
# ---------------------------------------------------------------------------
FROM ${BASE_IMAGE}
ARG VLLM_PIP_SPEC
ARG TORCH_INDEX_URL
ARG NCCL_PIP_SPEC
ARG INSTALL_OLLAMA

# ── Python ────────────────────────────────────────────────────────────────────
# Install Python 3.12 on bases that ship without Python (ubuntu:24.04).
# python:*-slim images already provide python3.12 — this block is skipped.
RUN if ! command -v python3.12 >/dev/null 2>&1; then \
        apt-get update \
        && apt-get install -y --no-install-recommends \
            python3.12 python3.12-venv curl ca-certificates \
        && rm -rf /var/lib/apt/lists/* \
        && ln -sf /usr/bin/python3.12 /usr/bin/python3 \
        && ln -sf /usr/bin/python3.12 /usr/bin/python; \
    fi

# ── Runtime JIT toolchain ─────────────────────────────────────────────────────
# vLLM (via Triton / FlashInfer) JIT-compiles CUDA kernels at runtime:
#   gcc            — host C compiler for Triton's ctypes extension build
#   g++            — FlashInfer compiles/links its C++ JIT modules with `c++`
#                    (previously pulled in implicitly by the apt cuda-nvcc
#                    package; must be explicit now)
#   python3.12-dev — Python.h (Triton compiles a small C module at startup)
#   libnuma1       — NUMA awareness for vLLM/NCCL
# nvcc/ptxas/headers come from the pip wheels — nothing CUDA is installed here.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc g++ python3.12-dev libnuma1 \
    && rm -rf /var/lib/apt/lists/*

# ── Virtualenv + Python dependencies ─────────────────────────────────────────
# Virtualenv keeps all packages self-contained and avoids the PEP 668
# "externally-managed-environment" lockdown on the system Python in noble.
# --seed adds pip inside the venv for in-container debugging.
ENV VIRTUAL_ENV=/opt/venv
ENV UV_PYTHON_DOWNLOADS=never
RUN --mount=type=bind,from=uv,source=/uv,target=/usr/local/bin/uv \
    uv venv --seed --python python3.12 /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY requirements.txt /tmp/requirements.txt
RUN --mount=type=bind,from=uv,source=/uv,target=/usr/local/bin/uv \
    uv pip install --no-cache -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

RUN --mount=type=bind,from=uv,source=/uv,target=/usr/local/bin/uv \
    set -e \
    # 1. Install vLLM (pins torch + the full CUDA 13 toolkit from PyPI)
    && uv pip install --no-cache "$VLLM_PIP_SPEC" \
    # 2. Optional: reinstall torch from a specific CUDA wheel index.
    #    Since vLLM ≥0.20, PyPI torch already includes CUDA support, so
    #    this is normally a no-op (TORCH_INDEX_URL defaults to empty).
    && if [ -n "$TORCH_INDEX_URL" ]; then \
         torch_ver=$(python3 -c "import importlib.metadata as m; print(m.version('torch'))") \
         && echo "Reinstalling torch==${torch_ver} from ${TORCH_INDEX_URL}" \
         && uv pip install --no-cache --reinstall --no-deps \
             --extra-index-url "$TORCH_INDEX_URL" \
             "torch==${torch_ver}"; \
       fi \
    # 3. Optional: override NCCL version
    && if [ -n "$NCCL_PIP_SPEC" ]; then \
         uv pip install --no-cache --reinstall --no-deps "$NCCL_PIP_SPEC"; \
       fi \
    # 4. Upgrade transformers for latest model architecture support
    && uv pip install --no-cache --upgrade transformers \
    # 5. FlashInfer (no-op while it ships as a vLLM dependency; kept so
    #    it stays installed if vLLM ever drops the dependency)
    && uv pip install --no-cache --no-deps flashinfer-python \
    # 6. Pin the CUDA compiler wheels to the runtime-header version.
    #    torch pins nvidia-cuda-runtime (the headers, CUDART_VERSION)
    #    but NOT nvidia-cuda-nvcc, so the resolver floats nvcc to the
    #    newest minor (e.g. nvcc 13.2 vs headers 13.0). FlashInfer's
    #    bundled CCCL rejects that at runtime — every JIT compile dies
    #    with "CUDA compiler and CUDA toolkit headers are incompatible"
    #    and the lane exits during startup.
    && cuda_mm=$(python3 -c "import importlib.metadata as m; print('.'.join(m.version('nvidia-cuda-runtime').split('.')[:2]))") \
    && uv pip install --no-cache \
         "nvidia-cuda-nvcc==${cuda_mm}.*" \
         "nvidia-cuda-crt==${cuda_mm}.*" \
         "nvidia-nvvm==${cuda_mm}.*" \
    # Strip test/benchmark payloads
    && { find /opt/venv -type d \( -name 'tests' -o -name 'test' -o -name 'benchmarks' \) \
         -path '*/torch/*' -exec rm -rf {} + || true; }

# ── CUDA toolkit prefix from the pip wheels ───────────────────────────────────
# CUDA_HOME/PATH make FlashInfer & friends resolve nvcc/headers/libs from the
# wheel-vendored toolkit (they honor CUDA_HOME, falling back to `which nvcc`).
# Set unconditionally (ENV can't be conditional).
ENV CUDA_HOME=/opt/venv/lib/python3.12/site-packages/nvidia/cu13
ENV PATH="${CUDA_HOME}/bin:$PATH"
RUN set -e; \
    # Guard: fail the build early if a future vLLM bump changes the
    # wheel toolkit layout this image depends on.
    test -x "$CUDA_HOME/bin/nvcc"; \
    test -f "$CUDA_HOME/include/cuda_runtime.h"; \
    # Guard: nvcc and the runtime headers must agree on the CUDA minor
    # version (see install step 6), or FlashInfer JIT fails at runtime.
    cudart=$(sed -n 's/^#define CUDART_VERSION[[:space:]]*\([0-9]*\).*/\1/p' "$CUDA_HOME/include/cuda_runtime_api.h"); \
    hdr_mm="$((cudart / 1000)).$((cudart % 1000 / 10))"; \
    nvcc_mm=$("$CUDA_HOME/bin/nvcc" --version | sed -n 's/.*release \([0-9][0-9]*\.[0-9][0-9]*\).*/\1/p'); \
    if [ "$hdr_mm" != "$nvcc_mm" ]; then \
      echo "CUDA minor version mismatch: nvcc $nvcc_mm vs runtime headers $hdr_mm" >&2; \
      exit 1; \
    fi; \
    # lib64 → lib (FlashInfer links with -L$CUDA_HOME/lib64)
    ln -sfn lib "$CUDA_HOME/lib64"; \
    # Unversioned dev symlinks (wheels only ship SONAME-versioned .so's)
    for so in "$CUDA_HOME"/lib/*.so.*; do \
      base="${so%%.so.*}.so"; \
      [ -e "$base" ] || ln -s "$(basename "$so")" "$base"; \
    done; \
    # Driver linker stub with SONAME libcuda.so.1, generated from the
    # wheel's own cuda.h. It must actually EXPORT the driver-API symbols:
    # GCC links with --as-needed by default, so an empty stub would be
    # discarded and JIT modules would end up with unresolved cu* symbols
    # and no DT_NEEDED entry for libcuda.so.1. Preprocessing cuda.h first
    # yields the real versioned symbol names (e.g. cuMemAlloc_v2). At
    # load time the SONAME binds to the real driver library injected by
    # the container runtime.
    mkdir -p "$CUDA_HOME/lib/stubs"; \
    echo '#include <cuda.h>' \
      | gcc -E -P -I "$CUDA_HOME/include" - \
      | tr '\n' ' ' \
      | grep -oE '\bcu[A-Z][A-Za-z0-9_]*[[:space:]]*\(' \
      | sed -E 's/[[:space:]]*\(//' | sort -u \
      | sed 's/.*/void &(void) {}/' > /tmp/libcuda_stub.c; \
    gcc -shared -fPIC -Wl,-soname,libcuda.so.1 \
        -o "$CUDA_HOME/lib/stubs/libcuda.so" /tmp/libcuda_stub.c; \
    # Guard: the stub must export the driver API surface (~450 functions
    # for CUDA 13; fail early if header parsing ever breaks).
    n="$(nm -D --defined-only "$CUDA_HOME/lib/stubs/libcuda.so" | grep -c ' T cu')"; \
    [ "$n" -ge 300 ] || { echo "libcuda stub exports only $n symbols" >&2; exit 1; }; \
    # Guard: a representative JIT-style link (FlashInfer links with
    # -L$CUDA_HOME/lib64/stubs -lcuda) must record DT_NEEDED libcuda.so.1.
    printf 'extern int cuInit(unsigned int u);\nint probe(void) { return cuInit(0); }\n' > /tmp/needed_probe.c; \
    gcc -shared -fPIC -o /tmp/needed_probe.so /tmp/needed_probe.c \
        -L "$CUDA_HOME/lib64/stubs" -lcuda; \
    readelf -d /tmp/needed_probe.so | grep -q 'NEEDED.*libcuda\.so\.1' \
      || { echo "JIT-style probe .so lacks DT_NEEDED libcuda.so.1" >&2; exit 1; }; \
    rm -f /tmp/libcuda_stub.c /tmp/needed_probe.c /tmp/needed_probe.so; \
    # Register wheel-vendored CUDA library directories with the dynamic
    # linker so child processes (vLLM lanes) can find them. Covers
    # nvidia/cu13/lib, cudnn, nccl, nvshmem, cusparselt and torch/lib
    # (libc10.so etc.) — none are in the default search path.
    { find /opt/venv/lib -path '*/nvidia/*/lib' -type d 2>/dev/null; \
      find /opt/venv/lib -path '*/torch/lib' -type d 2>/dev/null; \
    } > /etc/ld.so.conf.d/pip-cuda-libs.conf \
    && ldconfig

COPY --from=ollama-builder /ollama-root/ /
COPY logos_worker_node/ /app/logos_worker_node/
COPY tools/ /app/tools/
RUN mkdir -p /app/certs /app/data

# ---------------------------------------------------------------------------
# Runtime environment
# ---------------------------------------------------------------------------
ENV PYTHONUNBUFFERED=1
ENV LOGOS_WORKER_NODE_HAS_VLLM=1
ENV LOGOS_WORKER_NODE_HAS_OLLAMA=${INSTALL_OLLAMA}
ENV LOGOS_WORKER_NODE_CONFIG=/app/config.yml
ENV LOGOS_STATE_DIR=/app/data

# GPU visibility — plain Ubuntu base, so set what nvidia/cuda images used to.
# The NVIDIA Container Runtime keys host-driver injection off these.
ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility

# /usr/local/nvidia/lib64 — some injection setups place host driver libs here
# (wheel-vendored CUDA libs are resolved via the ldconfig entries above).
ENV LD_LIBRARY_PATH=/usr/local/nvidia/lib64

# NCCL — 2× Quadro RTX 5000 are PCIe-connected (no NVLink/NVSwitch)
ENV NCCL_IB_DISABLE=1
ENV NCCL_DEBUG=WARN

EXPOSE ${WORKER_PORT:-80}

CMD ["python3", "-m", "logos_worker_node.main"]
