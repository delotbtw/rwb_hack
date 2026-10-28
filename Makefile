COMPOSE := docker compose -f docker-compose.yml -f docker-compose.app.yml
COMPOSE_FULL := $(COMPOSE) -f docker-compose.realtime.yml -f docker-compose.bi.yml --profile realtime --profile bi
URL     := http://localhost:8000

.PHONY: all demo up etl notebook app bundle logs ps down reset help

all:  ## запустить приложение, Streamlit, поток и Grafana
	@test -f data/olist_orders_dataset.csv || { echo 'Не найдены исходные CSV в папке data/. Добавьте исходные файлы Olist и повторите make all.' >&2; exit 1; }
	$(COMPOSE_FULL) up -d --build --wait app web redpanda redpanda-console ingestor grafana
	$(MAKE) demo-replay

help:  ## список команд
	@grep -hE '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-8s %s\n", $$1, $$2}'

demo:  ## запустить приложение, Streamlit, поток и Grafana
	$(MAKE) all

up:  ## только база
	$(COMPOSE) up -d --wait postgres

etl:  ## пересобрать модель (FORCE_RAW=1 — перезалить raw, DQ_MODE=report — не откатывать)
	$(COMPOSE) run --rm etl

notebook:  ## импорт графиков из notebooks/*.ipynb без пересборки модели (EXECUTE=1 — перевыполнить)
	$(COMPOSE) run --rm -e EXECUTE=$(or $(EXECUTE),0) etl python -m pipeline.import_notebook

app:  ## перезапустить приложение (кэш графиков сбросится)
	$(COMPOSE) up -d --no-deps --force-recreate app

bundle:  ## собрать sql/** в dist/build_model.sql без запуска
	python3 -m pipeline.bundle

logs:  ## логи etl и app
	$(COMPOSE) logs --tail=100 etl app

ps:
	$(COMPOSE) ps -a

down:  ## остановить всё (данные сохраняются)
	docker compose -f docker-compose.yml -f docker-compose.app.yml -f docker-compose.realtime.yml -f docker-compose.bi.yml --profile realtime --profile bi down

reset:  ## снести базу с данными и собрать всё заново
	$(COMPOSE) down -v
	$(MAKE) demo

# Цели модулей real-time (K2 stream.mk, K3 batch.mk, K4 bi.mk) — каждый модуль ведёт свой файл
-include make/*.mk
