#!/usr/bin/env bash
# Запуск Capibara из корня проекта; существующие данные не удаляются.
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
    echo 'Нужен Docker Desktop с Docker Compose.' >&2
    exit 1
fi
if ! docker info >/dev/null 2>&1; then
    echo 'Запустите Docker Desktop и повторите команду.' >&2
    exit 1
fi
if [[ ! -f data/olist_orders_dataset.csv ]]; then
    echo 'Не найдены исходные CSV в папке data/.' >&2
    exit 1
fi

compose=(docker compose -f docker-compose.yml -f docker-compose.app.yml -f docker-compose.realtime.yml -f docker-compose.bi.yml)

echo 'Собираю модель и запускаю приложение…'
"${compose[@]}" up -d --build --wait app web

echo 'Запускаю поток и Grafana…'
"${compose[@]}" up -d --build --wait redpanda redpanda-console ingestor grafana

printf '\nГотово:\n  Streamlit: http://localhost:8501\n  Приложение и API: http://localhost:8000\n  Grafana: http://localhost:3000\n  Redpanda Console: http://localhost:8089\n\nДля запуска демонстрационного потока: make demo-replay\n'
