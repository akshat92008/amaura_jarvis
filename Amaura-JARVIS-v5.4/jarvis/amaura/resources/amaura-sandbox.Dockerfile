FROM node:22-bookworm-slim AS node_runtime

FROM python:3.12-slim-bookworm

ARG DEBIAN_FRONTEND=noninteractive

COPY --from=node_runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node_runtime /usr/local/lib/node_modules /usr/local/lib/node_modules

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        git \
        make \
        gcc \
        g++ \
        ripgrep \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && python -m pip install --no-cache-dir \
        mypy==1.20.2 \
        pytest==9.1.1 \
        ruff==0.16.0 \
    && useradd --create-home --uid 10001 amaura

ENV CI=1 \
    HOME=/tmp/amaura-home \
    XDG_CACHE_HOME=/tmp/amaura-cache \
    NPM_CONFIG_CACHE=/tmp/npm-cache \
    PIP_CACHE_DIR=/tmp/pip-cache \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER 10001:10001
WORKDIR /workspace

ENTRYPOINT []
