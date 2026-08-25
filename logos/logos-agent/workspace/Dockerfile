# The image an agent session runs in.
#
# It holds a coding agent, the tools it needs to do development work, and a
# browser for screenshots. It deliberately holds no credentials and no Docker
# client: everything privileged is done by the runner service outside this
# container (see app/docker_engine.py for the sandbox this image runs under).
FROM node:22-bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Playwright's browsers go somewhere the unprivileged user owns and the
    # read-only root filesystem still permits at build time.
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright

RUN apt-get update && apt-get install -y --no-install-recommends \
      git \
      ca-certificates \
      curl \
      gnupg \
      jq \
      ripgrep \
      python3 \
      python3-venv \
      python3-pip \
      # Chromium's runtime dependencies. Installed explicitly rather than via
      # `playwright install-deps` so the layer is reproducible.
      libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
      libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
      libgbm1 libpango-1.0-0 libcairo2 libasound2 \
  && rm -rf /var/lib/apt/lists/*

# A JDK, so a session can build and test logos-webservice. It targets Java 25
# (see logos-webservice/pom.xml), which Debian bookworm does not package at all,
# so it comes from Adoptium rather than from the distribution. The service's
# Maven wrapper (`./mvnw`) fetches Maven itself, so no separate Maven here.
ARG JDK_VERSION=25
RUN curl -fsSL https://packages.adoptium.net/artifactory/api/gpg/key/public \
      | gpg --dearmor -o /usr/share/keyrings/adoptium.gpg \
  && echo "deb [signed-by=/usr/share/keyrings/adoptium.gpg] https://packages.adoptium.net/artifactory/deb $(. /etc/os-release && echo "$VERSION_CODENAME") main" \
      > /etc/apt/sources.list.d/adoptium.list \
  && apt-get update \
  && apt-get install -y --no-install-recommends "temurin-${JDK_VERSION}-jdk" \
  && rm -rf /var/lib/apt/lists/*

# GitHub CLI, from the official apt repository.
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      -o /usr/share/keyrings/githubcli-archive-keyring.gpg \
  && chmod a+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
  && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
      > /etc/apt/sources.list.d/github-cli.list \
  && apt-get update && apt-get install -y --no-install-recommends gh \
  && rm -rf /var/lib/apt/lists/*

# uv, matching the pin used by the other Logos images.
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /usr/local/bin/uv

# Logos targets Python 3.13; Debian bookworm ships 3.11. Install the interpreter
# at build time into a shared location, so a session runs `uv venv --python
# 3.13` instantly instead of downloading ~30 MB on every run — and so it works
# at all, since the session's root filesystem is read-only.
ENV UV_PYTHON_INSTALL_DIR=/opt/uv-python
RUN uv python install 3.13 && chmod -R a+rX /opt/uv-python

# The coding agent itself — this image exists to run Claude Code — and
# Playwright for screenshots. Both pinned so a session's behaviour does not
# change under us between builds; bump them deliberately.
ARG CLAUDE_CODE_VERSION=2.1.245
ARG PLAYWRIGHT_VERSION=1.62.1
RUN npm install -g \
      "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
      "playwright@${PLAYWRIGHT_VERSION}" \
  && npm cache clean --force

RUN npx --yes playwright@${PLAYWRIGHT_VERSION} install chromium \
  && chmod -R a+rX /opt/playwright

# Unprivileged user. The runner starts the container as `agent`; nothing in a
# session ever runs as root.
RUN useradd --create-home --shell /bin/bash --uid 10001 agent \
  && mkdir -p /workspace /artifacts \
  && chown -R agent:agent /workspace /artifacts /home/agent

COPY --chown=agent:agent logos/logos-agent/workspace/run_session.py /usr/local/lib/run_session.py
COPY --chown=agent:agent logos/logos-agent/workspace/screenshot.js /usr/local/lib/screenshot.js

USER agent
WORKDIR /workspace

# HOME lives on the workspace volume: the root filesystem is read-only, and
# keeping agent state (git config, CLI caches) with the working copy means a
# follow-up session in the same workspace resumes with it intact.
ENV HOME=/workspace/.home \
    NODE_PATH=/usr/local/lib/node_modules

ENTRYPOINT ["python3", "/usr/local/lib/run_session.py"]
