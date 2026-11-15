"""One fetcher per AMC. Each exposes fetch(month, dest_dir) -> FetchReport."""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class FetchReport:
    amc: str
    listed: int = 0
    downloaded: int = 0
    skipped: int = 0  # already on disk
    notes: list[str] = field(default_factory=list)


def month_parts(month: str) -> tuple[int, int, str]:
    """'2026-10' -> (2026, 10, 'October')"""
    y, m = (int(x) for x in month.split("-"))
    if not 1 <= m <= 12:
        raise ValueError(f"bad month: {month}")
    return y, m, calendar.month_name[m]


def registry() -> dict[str, Callable[[str, Path], FetchReport]]:
    from . import axis, hdfc, motilal, navi, nippon, ppfas

    return {
        "nippon": nippon.fetch,
        "hdfc": hdfc.fetch,
        "axis": axis.fetch,
        "motilal": motilal.fetch,
        "navi": navi.fetch,
        "ppfas": ppfas.fetch,
    }
