# K4: Grafana (BI как код). Подключается из Makefile через `-include make/*.mk`.
#   make bi       - поднять Grafana на http://localhost:3000 (anonymous Viewer, datasource capibara-pg, папка Capibara)
#   make bi-stop  - остановить и удалить ТОЛЬКО контейнер grafana (postgres и остальное не трогаем)
# Требуется запущенный postgres с собранной моделью (`make all`).

BI_COMPOSE := docker compose -f docker-compose.yml -f docker-compose.bi.yml --profile bi

.PHONY: bi bi-stop

bi:
	$(BI_COMPOSE) up -d --wait grafana
	@echo "Grafana: http://localhost:3000 (без логина, роль Viewer)"

bi-stop:
	$(BI_COMPOSE) rm -sf grafana
