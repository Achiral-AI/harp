# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Build dependencies are installed up front so layer cache survives source edits.
COPY pyproject.toml ./pyproject.toml
COPY src ./src

# Vendor the pre-generated python proto bindings into the package.
COPY vendor/warp-proto-apis/apis/multi_agent/v1/gen/python ./src/harp/proto

# Mark the proto dir as a regular package so relative imports work.
RUN touch ./src/harp/proto/__init__.py

RUN pip install --upgrade pip && \
    pip install .

EXPOSE 8787

ENV SHIM_HOST=0.0.0.0 \
    SHIM_PORT=8787

CMD ["python", "-m", "harp"]
