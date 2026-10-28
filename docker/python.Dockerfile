# Один образ для etl и app: только зависимости, код монтируется из репозитория (./ → /work).
# python:3.12-slim мультиархитектурный — на Apple Silicon собирается нативный arm64, без эмуляции.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg

WORKDIR /work
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    # прогрев кэша шрифтов matplotlib: иначе первый график рисуется ~15 с
    && python -c "import matplotlib.pyplot"
