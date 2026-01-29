# syntax=docker/dockerfile:1.21

FROM ghcr.io/astral-sh/uv:python3.12-trixie-slim AS uv-tools

FROM python:3.14-slim AS builder

ARG DEBIAN_FRONTEND=noninteractive

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        build-essential \
        git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv-tools /usr/local/bin/uv /usr/bin/

WORKDIR /app

COPY pyproject.toml README.md uv.lock ./
COPY src ./src

RUN uv build --wheel --out-dir /dist && \
    uv export \
        --format requirements-txt \
        --group ta \
        --no-emit-project \
        --output-file /dist/requirements.txt

FROM python:3.14-slim

ARG DEBIAN_FRONTEND=noninteractive

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        ca-certificates \
        git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv-tools /usr/local/bin/uv /usr/bin/

WORKDIR /workspace

COPY --from=builder /dist/ /tmp/dist/

RUN uv pip install --system --no-cache -r /tmp/dist/requirements.txt \
    && uv pip install --system --no-cache /tmp/dist/*.whl \
    && rm -rf /tmp/dist

LABEL org.opencontainers.image.title="Schwab MCP Server" \
      org.opencontainers.image.description="Model Context Protocol server for Schwab built on schwab-mcp." \
      org.opencontainers.image.source="https://github.com/jkoelker/schwab-mcp"

ENTRYPOINT ["schwab-mcp"]
CMD ["server"]
