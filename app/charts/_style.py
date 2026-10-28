"""Общий стиль графиков — чтобы все PNG выглядели одинаково."""

from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

ACCENT = "#2563eb"
MUTED = "#94a3b8"


def new_figure(width: float = 10, height: float = 4.8) -> tuple[Figure, "Axes"]:  # noqa: F821
    fig = Figure(figsize=(width, height), dpi=110)
    ax = fig.add_subplot()
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.3)
    return fig, ax


def money(x, _pos=None) -> str:
    if abs(x) >= 1e6:
        return f"{x / 1e6:.1f} млн"
    if abs(x) >= 1e3:
        return f"{x / 1e3:.0f} тыс"
    return f"{x:.0f}"


MONEY = FuncFormatter(money)
