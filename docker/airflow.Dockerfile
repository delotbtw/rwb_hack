# syntax=docker/dockerfile:1
# Образ Airflow для ночной сборки (K3, docs/realtime/K3-batch.md §3.6).
# Версия 2.11.x, а не 3.x: 3.x требует отдельные api-server, dag-processor и triggerer (лишние контейнеры).
# Тег apache/airflow:<версия>-python3.12 уже собран с официальными constraints; патч-версию обновляйте здесь (ASSUMPTION K3-4).
ARG AIRFLOW_VERSION=2.11.2
ARG PYTHON_VERSION=3.12
FROM apache/airflow:${AIRFLOW_VERSION}-python${PYTHON_VERSION}

ARG AIRFLOW_VERSION
ARG PYTHON_VERSION
# Любые дополнительные пакеты ставить только с этими constraints, иначе pip сдвинет версии самого Airflow.
ENV AIRFLOW_CONSTRAINTS_URL=https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

# pipeline/ использует только psycopg2 (он входит в провайдер postgres образа); код монтируется из репозитория (./ → /work).
# Проверка на сборке: пин версии не уехал, нужный драйвер на месте.
RUN test "$(airflow version)" = "${AIRFLOW_VERSION}" && python -c "import psycopg2"

# pytest для проверки DAG (A-10) внутри образа; версия из constraints Airflow.
RUN pip install --no-cache-dir "pytest==8.2.1" --constraint "${AIRFLOW_CONSTRAINTS_URL}"

WORKDIR /work
