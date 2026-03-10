ARG PYTHON_IMAGE=python:3.12-slim
ARG INSTALL_VLLM=1
ARG VLLM_PIP_SPEC=vllm
ARG INSTALL_OLLAMA=1

# ---- optional ollama payload ----
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
          *) echo "Unsupported architecture for bundled Ollama: $arch" >&2; exit 1 ;; \
        esac; \
        asset="ollama-linux-${ollama_arch}.tar.zst"; \
        release_json="$(curl -fsSL https://api.github.com/repos/ollama/ollama/releases/latest)"; \
        download_url="$(printf '%s' "$release_json" | jq -r --arg asset "$asset" '.assets[] | select(.name == $asset) | .browser_download_url' | head -n1)"; \
        if [ -z "$download_url" ] || [ "$download_url" = "null" ]; then \
          tag="$(printf '%s' "$release_json" | jq -r '.tag_name')"; \
          if [ -z "$tag" ] || [ "$tag" = "null" ]; then \
            echo "Could not resolve latest Ollama release tag from GitHub API" >&2; \
            exit 1; \
          fi; \
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
          echo "Bundled Ollama binary not found in downloaded archive" >&2; \
          exit 1; \
        fi; \
        if [ -d /tmp/ollama-extract/lib/ollama ]; then \
          cp -a /tmp/ollama-extract/lib/ollama /ollama-root/usr/local/lib/ollama; \
        fi; \
        chmod +x /ollama-root/usr/local/bin/ollama; \
      fi

# ---- build ----
FROM ${PYTHON_IMAGE} AS builder
ARG INSTALL_VLLM
ARG VLLM_PIP_SPEC

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt \
    && if [ "$INSTALL_VLLM" = "1" ]; then \
        pip install --no-cache-dir --prefix=/install "$VLLM_PIP_SPEC"; \
    fi

# ---- runtime ----
FROM ${PYTHON_IMAGE}
ARG INSTALL_VLLM
ARG INSTALL_OLLAMA

# curl is useful for health checks and debugging
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libnuma1 ca-certificates \
    && if [ "$INSTALL_VLLM" = "1" ]; then \
        apt-get install -y --no-install-recommends build-essential; \
    fi \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /install /usr/local
COPY --from=ollama-builder /ollama-root/ /
COPY node_controller/ /app/node_controller/
RUN mkdir -p /app/certs

ENV PYTHONUNBUFFERED=1
ENV NODE_CONTROLLER_HAS_VLLM=${INSTALL_VLLM}
ENV NODE_CONTROLLER_HAS_OLLAMA=${INSTALL_OLLAMA}

EXPOSE 8444

CMD ["python", "-m", "node_controller.main"]
