# Цели K3: Airflow и демо-режим cutoff (docs/realtime/K3-batch.md §3.6, §3.7). Подключается из Makefile через -include make/*.mk.
# COMPOSE и $(MAKE) берутся из Makefile; профиль airflow добавляет docker-compose.airflow.yml.

AIRFLOW_COMPOSE := $(COMPOSE) -f docker-compose.airflow.yml --profile airflow
AIRFLOW_URL     := http://localhost:8082
# Граница демо «история + хвост»: заказы с purchased_at >= CUTOFF в модель не попадают.
CUTOFF          ?= 2018-08-01

.PHONY: airflow airflow-down demo-prep demo-reset

airflow:  ## Airflow (БД airflow, scheduler, UI :8082, admin/admin)
	$(AIRFLOW_COMPOSE) up -d --build --wait airflow-webserver airflow-scheduler
	@echo "Airflow UI: $(AIRFLOW_URL) (DAG capibara_daily стартует на паузе — включить в UI)"

airflow-down:  ## остановить Airflow (postgres и приложение не трогает; БД airflow сохраняется)
	$(AIRFLOW_COMPOSE) rm -sf airflow-webserver airflow-scheduler airflow-init

demo-prep:  ## демо: модель до CUTOFF (по умолчанию 2018-08-01) без сброса потока
	$(COMPOSE) run --rm -e CUTOFF=$(CUTOFF) etl python -m pipeline.demo prep

demo-reset:  ## демо с нуля: сброс брокера (stream-reset), landing, ops.replay_runs, модель до CUTOFF
	$(MAKE) stream-reset
	$(COMPOSE) run --rm -e CUTOFF=$(CUTOFF) etl python -m pipeline.demo reset
