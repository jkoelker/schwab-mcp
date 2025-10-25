# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS builder

ARG DEBIAN_FRONTEND=noninteractive

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install --no-install-recommends -y build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src

# hadolint ignore=DL3013
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir build \
    && python -m build --wheel --outdir /dist

FROM python:3.12-slim AS runtime

ARG DEBIAN_FRONTEND=noninteractive

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_ROOT_USER_ACTION=ignore \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install --no-install-recommends -y ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

COPY --from=builder /dist/ /tmp/dist/

RUN pip install --no-cache-dir /tmp/dist/*.whl \
    && rm -rf /tmp/dist

LABEL org.opencontainers.image.title="Schwab MCP Server" \
      org.opencontainers.image.description="Model Context Protocol server for Schwab built on schwab-mcp." \
      org.opencontainers.image.source="https://github.com/jkoelker/schwab-mcp"

ENTRYPOINT ["schwab-mcp"]
CMD ["server"]
