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
      jq \
      ripgrep \
      python3 \
      python3-venv \
      python3-pip \
      openjdk-21-jdk-headless \
      # Chromium's runtime dependencies. Installed explicitly rather than via
      # `playwright install-deps` so the layer is reproducible.
      libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
      libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
      libgbm1 libpango-1.0-0 libcairo2 libasound2 \
  && rm -rf /var/lib/apt/lists/*

# GitHub CLI, from the official apt repository.
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      -o /usr/share/keyrings/githubcli-archive-keyring.gpg \
  && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
      > /etc/apt/sources.list.d/github-cli.list \
  && apt-get update && apt-get install -y --no-install-recommends gh \
  && rm -rf /var/lib/apt/lists/*

# uv, matching the pin used by the other Logos images.
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /usr/local/bin/uv

# The coding agent itself, and Playwright for screenshots. Both pinned so a
# session's behaviour does not change under us between builds.
ARG CLAUDE_CODE_VERSION=2.0.1
ARG PLAYWRIGHT_VERSION=1.49.1
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
