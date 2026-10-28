# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /work
COPY requirements/web.txt /tmp/requirements/web.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r /tmp/requirements/web.txt \
    && useradd --create-home --uid 10001 web
USER web
