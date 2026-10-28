"""Шум потока (--noise, K2 §4): ~1 % дублей и перестановок соседних событий разных заказов."""

import random

from stream.generator.dataset import Event

NOISE_RATE = 0.01
MAX_DUP_DELAY = 50  # дубль приходит не позже чем через столько сообщений
SEED = 42


def add_noise(events: list[Event], rate: float = NOISE_RATE, seed: int = SEED) -> list[Event]:
    """Порядок событий одного заказа не нарушается (created остаётся первым): меняются только соседи разных заказов."""
    rng = random.Random(seed)
    shuffled = list(events)
    i = 0
    while i < len(shuffled) - 1:
        if rng.random() < rate / 2 and shuffled[i].order_id != shuffled[i + 1].order_id:
            shuffled[i], shuffled[i + 1] = shuffled[i + 1], shuffled[i]
            i += 1
        i += 1

    late: dict[int, list[Event]] = {}
    for i, event in enumerate(shuffled):
        if rng.random() < rate / 2:
            late.setdefault(i + rng.randint(1, MAX_DUP_DELAY), []).append(event)

    result: list[Event] = []
    for i, event in enumerate(shuffled):
        result.append(event)
        result.extend(late.pop(i, []))
    for position in sorted(late):
        result.extend(late[position])
    return result
