"""K3-T4 (A-10): DAG `capibara_daily` импортируется без ошибок и имеет заданную структуру.

Без airflow (образ capibara-python:dev) тест пропускается; работает в контейнере Airflow.
БД не нужна: импорт DAG только создаёт объекты.
"""
import pathlib

import pytest

# каталог airflow/ в корне репозитория виден как namespace-пакет, поэтому проверяем настоящий модуль
pytest.importorskip("airflow.models")

from airflow.models import DagBag  # noqa: E402

DAGS_DIR = pathlib.Path(__file__).resolve().parents[2] / "airflow" / "dags"
TASKS = ["extract", "load_raw", "snapshot_stream", "build", "dq", "reconcile", "publish", "report"]


@pytest.fixture(scope="module")
def dag_bag():
    return DagBag(dag_folder=str(DAGS_DIR), include_examples=False)


@pytest.fixture(scope="module")
def dag(dag_bag):
    return dag_bag.get_dag("capibara_daily")


def test_no_import_errors(dag_bag):
    assert dag_bag.import_errors == {}


def test_dag_settings(dag):
    assert dag is not None
    assert dag.schedule_interval == "@daily"
    assert dag.catchup is True
    assert dag.max_active_runs == 1


def test_tasks_chain_in_order(dag):
    assert [t.task_id for t in dag.topological_sort()] == TASKS
    for upstream, downstream in zip(TASKS, TASKS[1:]):
        assert dag.get_task(upstream).downstream_task_ids == {downstream}
    assert dag.get_task("report").downstream_task_ids == set()


def test_retries_and_failure_callback(dag):
    for task in dag.tasks:
        assert task.retries == (3 if task.task_id == "extract" else 0)
        assert task.on_failure_callback is not None
