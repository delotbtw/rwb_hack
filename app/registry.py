"""Реестр графиков. Новый график = функция с декоратором @chart в любом модуле app/charts/.

    @chart("revenue_by_month", "Выручка по месяцам", "Одно предложение-легенда.")
    def revenue_by_month(conn) -> Figure: ...

Функция получает открытое соединение, читает ТОЛЬКО mart.* и возвращает matplotlib Figure.
pyplot не использовать: у него глобальное состояние, а запросы рисуются параллельно.
"""

from dataclasses import dataclass
from typing import Callable

from matplotlib.figure import Figure


SECTIONS = ["Продажи", "Доставка и отзывы", "Качество данных"]


@dataclass(frozen=True)
class Chart:
    id: str
    title: str
    caption: str
    render: Callable[..., Figure]
    order: int
    section: str


REGISTRY: dict[str, Chart] = {}


def chart(chart_id: str, title: str, caption: str, order: int = 100, section: str = SECTIONS[0]):
    def decorator(fn: Callable[..., Figure]):
        if chart_id in REGISTRY:
            raise ValueError(f"График {chart_id!r} уже зарегистрирован")
        if section not in SECTIONS:
            raise ValueError(f"Неизвестный раздел {section!r}, допустимы: {SECTIONS}")
        REGISTRY[chart_id] = Chart(chart_id, title, caption, fn, order, section)
        return fn

    return decorator


def ordered() -> list[Chart]:
    return sorted(REGISTRY.values(), key=lambda c: (c.order, c.id))


def by_section() -> list[tuple[str, list[Chart]]]:
    charts = ordered()
    return [(s, [c for c in charts if c.section == s]) for s in SECTIONS if any(c.section == s for c in charts)]
