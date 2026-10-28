# syntax=docker/dockerfile:1
# Один образ для etl и app: только зависимости, код монтируется из репозитория (./ → /work).
# python:3.12-slim мультиархитектурный — на Apple Silicon собирается нативный arm64, без эмуляции.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /work

# Слой 1 (тяжёлый, редко меняется): пересобирается только при правке requirements/base.txt.
# Cache mount хранит скачанные wheel-файлы между сборками: при смене версии докачивается только новое.
COPY requirements/base.txt /tmp/requirements/base.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r /tmp/requirements/base.txt \
    # прогрев кэша шрифтов matplotlib: иначе первый график рисуется ~15 с
    && python -c "import matplotlib.pyplot"

# Слой 2 (лёгкий, меняется часто): правка requirements/app.txt не трогает слой 1.
COPY requirements/app.txt /tmp/requirements/app.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r /tmp/requirements/app.txt
