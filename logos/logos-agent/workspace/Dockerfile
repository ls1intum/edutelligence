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
#
# 3.12 as well, and not as a spare: Athena's nbstripout hook pins
# `language_version: python3.12`, and without that interpreter its hook
# environment cannot be built at all.
ENV UV_PYTHON_INSTALL_DIR=/opt/uv-python
RUN uv python install 3.13 3.12 && chmod -R a+rX /opt/uv-python

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

# The repository's own linters, installed at build time because a session has
# no network to install them with. Without this an agent cannot run what the
# house rules ask it to run: `pre-commit` fetches every hook from GitHub the
# first time, `pip install black` reaches PyPI, and the sandbox reaches
# neither. Sessions were pushing unformatted code and finding out from a red
# check nobody told them about.
#
# Every config in the monorepo, not just Logos's. The root config delegates
# to iris/, athena/ and memiris/ through sub-pre-commit, and those pin their
# own versions of the same tools — black 26.1.0 where Logos pins 25.1.0.
# Seeding one config would leave a session working on Iris reformatting its
# files with the wrong black, which is worse than not linting at all.
#
# The environments are keyed by hook repository and revision, so they are
# reused as long as the pinned revisions in the configs match. When they stop
# matching, the session's `pre-commit run` says so rather than silently
# skipping — which is why the configs are copied in and resolved here, not
# guessed.
# A venv of its own at the shared location the other Logos images use, not
# a tool install under /root: the session runs as `agent`, and everything it
# needs has to be readable without opening up root's home. Deliberately no
# VIRTUAL_ENV — this venv holds the linters, and a session building the
# project makes its own; pointing uv at this one would only confuse it.
ENV PATH=/opt/venv/bin:$PATH \
    PRE_COMMIT_STORE=/opt/pre-commit
COPY .pre-commit-config.yaml /tmp/hooks/.pre-commit-config.yaml
COPY logos/.pre-commit-config.yaml /tmp/hooks/logos/.pre-commit-config.yaml
COPY iris/.pre-commit-config.yaml /tmp/hooks/iris/.pre-commit-config.yaml
COPY athena/.pre-commit-config.yaml /tmp/hooks/athena/.pre-commit-config.yaml
COPY memiris/.pre-commit-config.yaml /tmp/hooks/memiris/.pre-commit-config.yaml
RUN uv venv --python 3.13 /opt/venv \
  && uv pip install --python /opt/venv pre-commit \
  && cd /tmp/hooks \
  && git init -q . \
  && git config user.email agent@logos.invalid \
  && git config user.name agent \
  && for config in \
       .pre-commit-config.yaml \
       logos/.pre-commit-config.yaml \
       iris/.pre-commit-config.yaml \
       athena/.pre-commit-config.yaml \
       memiris/.pre-commit-config.yaml; do \
       PRE_COMMIT_HOME=/opt/pre-commit pre-commit install-hooks --config "$config" || exit 1; \
     done \
  && chmod -R a+rX /opt/pre-commit /opt/venv \
  && rm -rf /tmp/hooks

# Unprivileged user. The runner starts the container as `agent`; nothing in a
# session ever runs as root.
RUN useradd --create-home --shell /bin/bash --uid 10001 agent \
  && mkdir -p /workspace /artifacts \
  && chown -R agent:agent /workspace /artifacts /home/agent

COPY --chown=agent:agent logos/logos-agent/workspace/run_session.py /usr/local/lib/run_session.py
COPY --chown=agent:agent logos/logos-agent/workspace/screenshot.js /usr/local/lib/screenshot.js

USER agent
WORKDIR /workspace

# HOME lives on the workspace volume because the root filesystem is
# read-only. The harness replaces it at the start of every session — a
# previous session is untrusted, and a credential-bearing session must not
# read the hooks, dotfiles, or poisoned caches it left — so nothing stored
# here is meant to survive a session.
#
# pre-commit's store goes with it, because a store is not read-only: it
# takes a lock file and writes to its little sqlite database on every run,
# and the seeded one at /opt/pre-commit is on the read-only root filesystem.
# The harness gives each session a store of its own holding a copy of the
# seeded database, whose rows point back at the hook environments in /opt —
# reading those is all pre-commit does with them once they are installed.
ENV HOME=/workspace/.home \
    PRE_COMMIT_HOME=/workspace/.home/pre-commit \
    NODE_PATH=/usr/local/lib/node_modules

ENTRYPOINT ["python3", "/usr/local/lib/run_session.py"]
