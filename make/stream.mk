# Цели потока real-time (K2). Подключается из Makefile строкой `-include make/*.mk`.
# CUTOFF/DURATION можно переопределить: make demo-replay CUTOFF=2018-07-01 DURATION=30
# Останавливать поток только через `make stream-stop` (не `down`: он снесёт базу и приложение).

COMPOSE_RT := $(COMPOSE) -f docker-compose.realtime.yml --profile realtime
CUTOFF     ?= 2018-08-01
DURATION   ?= 60

.PHONY: live demo-replay stream-reset stream-stop stream.generator stream.ingestor

live:  ## поток: postgres, redpanda, console (http://localhost:8089), ingestor — до healthy
	$(COMPOSE_RT) up -d --wait postgres redpanda redpanda-console ingestor

demo-replay: live  ## реплей хвоста с CUTOFF за DURATION секунд + статус потока
	$(COMPOSE_RT) run --rm generator --cutoff $(CUTOFF) --duration $(DURATION)
	@$(COMPOSE_RT) exec -T postgres psql -U hack -d marketplace -x -c "SELECT * FROM ops.stream_status"

stream-reset:  ## стереть топики и группу в брокере; ingestor остаётся остановленным до make live
	$(COMPOSE_RT) stop ingestor
	$(COMPOSE_RT) run --rm --entrypoint python generator -m stream.broker_reset

stream-stop:  ## остановить сервисы потока (данные брокера и БД сохраняются)
	$(COMPOSE_RT) stop ingestor redpanda-console redpanda

stream.generator:  ## только генератор: make stream.generator ARGS="--cutoff 2018-08-01 --duration 60"
	$(COMPOSE_RT) run --rm generator $(ARGS)

stream.ingestor:  ## только ingestor (в фоне)
	$(COMPOSE_RT) up -d --wait ingestor
