"""Паузы между событиями (K2 §4 п.4). Чистые функции: время не читают и не ждут."""

from bisect import bisect_left
from datetime import datetime
from itertools import accumulate
from typing import Sequence

DAY_SECONDS = 86400.0
DURATION_FILL = 0.95  # доля S, на которую подбирается сумма пауз: остаётся запас внутри [0.9 S, S]


def _deltas(times: Sequence[datetime]) -> list[float]:
    return [max((cur - prev).total_seconds(), 0.0) for prev, cur in zip(times, times[1:])]


def _fit_k(deltas: list[float], max_gap: float, target: float) -> float:
    """k, при котором sum(min(k * d, max_gap)) = target; если даже при max_gap на каждую паузу мало - inf."""
    ordered = sorted(deltas)
    prefix = [0.0, *accumulate(ordered)]
    n = len(ordered)

    def total(k: float) -> float:
        split = bisect_left(ordered, max_gap / k) if k > 0 else n
        return k * prefix[split] + max_gap * (n - split)

    positive = sum(1 for d in ordered if d > 0)
    if max_gap * positive <= target:
        return float("inf")
    low, high = 0.0, 1.0
    while total(high) < target:
        high *= 2
    for _ in range(100):
        mid = (low + high) / 2
        if total(mid) < target:
            low = mid
        else:
            high = mid
    return high


def _pause(k: float, delta: float, max_gap: float) -> float:
    if delta <= 0:
        return 0.0
    return max_gap if k == float("inf") else min(k * delta, max_gap)


def schedule(
    times: Sequence[datetime], duration: float | None = None, max_gap: float = 0.2
) -> list[float]:
    """Паузы (секунды) перед каждым событием; times - event_ts в порядке отправки, пауза перед первым 0.

    Пауза = min(k * dt, max_gap), dt - разница event_ts с предыдущим (не меньше 0). Без duration
    1 день = 1 с; с duration коэффициент k подбирается так, что сумма пауз ~ 0.95 * duration.
    """
    if not times:
        return []
    deltas = _deltas(times)
    k = 1.0 / DAY_SECONDS
    if duration is not None:
        k = _fit_k(deltas, max_gap, duration * DURATION_FILL)
    return [0.0, *(_pause(k, d, max_gap) for d in deltas)]
