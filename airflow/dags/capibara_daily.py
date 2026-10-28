"""DAG ночной сборки модели Capibara (docs/realtime/K3-batch.md §3.5).

extract → load_raw → snapshot_stream → build → dq → reconcile → publish → report

Каждая задача вызывает шаг из `pipeline/`; `run_id` создаёт `extract` и отдаёт остальным через XCom.
Cutoff по умолчанию NULL (полная сборка); для демо его можно передать в `dag_run.conf`: {"cutoff": "2018-08-01"}.
Пауза потока ставится в `build`, снимается в `publish`, `reconcile` (blocked) и в `on_failure_callback`.
Переменные окружения: CAPIBARA_START_DATE (по умолчанию 2026-10-20), FORCE_RAW (1 — перезалить raw).
"""

import os
from datetime import date, datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

from pipeline import daily_report, reconcile, steps

START_DATE = datetime.fromisoformat(os.getenv("CAPIBARA_START_DATE", "2026-10-20"))
EXTRACT_TASK = "extract"


def _ds(context) -> date:
    return date.fromisoformat(context["ds"])


def _cutoff(context) -> date | None:
    value = (context["dag_run"].conf or {}).get("cutoff")
    return date.fromisoformat(value) if value else None


def _run_id(context) -> int:
    return int(context["ti"].xcom_pull(task_ids=EXTRACT_TASK))


def task_extract(**context) -> int:
    steps.ensure_ops()
    run_id = steps.open_run(_ds(context), "batch", _cutoff(context))
    steps.extract(run_id, _ds(context))
    return run_id


def task_load_raw(**context) -> None:
    steps.load_raw(_run_id(context), force=os.getenv("FORCE_RAW") == "1")


def task_snapshot_stream(**context) -> None:
    run_id = _run_id(context)
    steps.pause_stream(run_id)  # пауза идемпотентна: снимок должен лечь после неё, build повторит вызов
    reconcile.snapshot_stream(run_id)


def task_build(**context) -> None:
    steps.build(_run_id(context), _cutoff(context))


def task_dq(**context) -> None:
    steps.dq(_run_id(context))


def task_reconcile(**context) -> None:
    reconcile.reconcile(_run_id(context), strict=True)


def task_publish(**context) -> None:
    steps.publish(_run_id(context))


def task_report(**context) -> None:
    daily_report.report(_run_id(context), _ds(context))


def on_failure(context) -> None:
    """Запуск → failed (blocked/published не меняются) и снятие паузы; без run_id (упал extract) запуск открывается."""
    run_id = context["ti"].xcom_pull(task_ids=EXTRACT_TASK)
    steps.mark_failed(int(run_id) if run_id is not None else None, _ds(context), context.get("exception"))


with DAG(
    dag_id="capibara_daily",
    schedule="@daily",
    start_date=START_DATE,
    catchup=True,
    max_active_runs=1,
    default_args={"retries": 0, "on_failure_callback": on_failure},
    tags=["capibara", "batch"],
) as dag:
    tasks = [
        PythonOperator(
            task_id=task_id,
            python_callable=fn,
            **({"retries": 3, "retry_delay": timedelta(minutes=1)} if task_id == EXTRACT_TASK else {}),
        )
        for task_id, fn in (
            (EXTRACT_TASK, task_extract),
            ("load_raw", task_load_raw),
            ("snapshot_stream", task_snapshot_stream),
            ("build", task_build),
            ("dq", task_dq),
            ("reconcile", task_reconcile),
            ("publish", task_publish),
            ("report", task_report),
        )
    ]
    for upstream, downstream in zip(tasks, tasks[1:]):
        upstream >> downstream
