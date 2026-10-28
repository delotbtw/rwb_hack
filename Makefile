COMPOSE := docker compose -f docker-compose.yml -f docker-compose.app.yml
URL     := http://localhost:8000

.PHONY: demo up etl notebook app bundle logs ps down reset help

help:  ## список команд
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-8s %s\n", $$1, $$2}'

demo:  ## всё одной командой: база → raw → модель → DQ → приложение
	$(COMPOSE) up -d --build app
	@$(COMPOSE) logs --no-log-prefix etl
	@printf "Жду приложение"; for i in $$(seq 1 60); do \
		curl -sf $(URL)/health >/dev/null && { echo; echo "Готово: $(URL)"; exit 0; }; printf "."; sleep 1; done; \
		echo; echo "Приложение не ответило, см. make logs"; exit 1

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
	$(COMPOSE) down

reset:  ## снести базу с данными и собрать всё заново
	$(COMPOSE) down -v
	$(MAKE) demo

# Цели модулей real-time (K2 stream.mk, K3 batch.mk, K4 bi.mk) — каждый модуль ведёт свой файл
-include make/*.mk
