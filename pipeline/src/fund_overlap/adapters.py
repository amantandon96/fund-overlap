"""Per-AMC knowledge that the shared sheet parser does not have.

Each adapter says where a scheme's title lives in the rows above the header,
and which weight convention to assume if a sheet has no Grand Total row.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date
from typing import Callable, Sequence

from .parser import _text

Preamble = Sequence[Sequence]


def _row_texts(row: Sequence) -> list[str]:
    """Distinct non-empty strings of a row, in order (merged cells repeat values)."""
    seen: list[str] = []
    for c in row:
        t = _text(c)
        if t and t not in seen:
            seen.append(t)
    return seen


def _cell_text(preamble: Preamble, r: int, c: int) -> str:
    if r < len(preamble) and c < len(preamble[r]):
        return _text(preamble[r][c])
    return ""


def _title_nippon(p: Preamble) -> str:
    return _cell_text(p, 0, 1)


def _title_hdfc(p: Preamble) -> str:
    return _cell_text(p, 0, 0)


def _title_axis(p: Preamble) -> str:
    return _cell_text(p, 0, 1)


def _title_motilal(p: Preamble) -> str:
    # "... STATEMENT AS ON <date>", blank, scheme name, "(An open ended ...)"
    lines = [t[0] for t in (_row_texts(r) for r in p) if t]
    for i, line in enumerate(lines):
        if re.match(r"\(?\s*an?\s+(open|close|interval)", line, re.I) and i > 0:
            # One sheet omits the brackets around the descriptor.
            descriptor = line if line.startswith("(") else f"({line})"
            return f"{lines[i - 1]} {descriptor}"
    return lines[-1] if lines else ""


def _title_ppfas(p: Preamble) -> str:
    # Title is the first filled cell of the first row; one sheet has a blank cell before it.
    for row in p:
        texts = _row_texts(row)
        if texts:
            return texts[0]
    return ""


def _title_navi(p: Preamble) -> str:
    for row in p:
        for t in _row_texts(row):
            low = t.lower()
            if low == "navi mutual fund" or low.startswith("monthly portfolio"):
                continue
            return t
    return ""


@dataclass(frozen=True)
class Adapter:
    amc: str
    display_name: str
    title: Callable[[Preamble], str]
    default_unit: str  # used only when a sheet has no Grand Total row
    skip_sheets: tuple[str, ...] = ("index",)
    multi_equity: bool = False  # overseas equity sits under a second "Equity & Equity related" heading


ADAPTERS: dict[str, Adapter] = {
    "nippon": Adapter("nippon", "Nippon India", _title_nippon, "fraction"),
    "hdfc": Adapter("hdfc", "HDFC", _title_hdfc, "percent"),
    "axis": Adapter("axis", "Axis", _title_axis, "fraction"),
    "motilal": Adapter("motilal", "Motilal Oswal", _title_motilal, "percent"),
    "navi": Adapter("navi", "Navi", _title_navi, "percent"),
    "ppfas": Adapter("ppfas", "Parag Parikh", _title_ppfas, "fraction", multi_equity=True),
}

_DESCRIPTOR = re.compile(r"\(\s*an?\s+(open|close|interval)", re.I)
_CUT = re.compile(
    r"\(\s*(an?\s+(open|close|interval)|formerly|erstwhile|previously)|\s+-\s+an?\s+open", re.I
)
_ACRONYMS = {
    "ETF", "FOF", "FOFS", "PSU", "BSE", "NSE", "IT", "ELSS", "US", "MNC", "ESG", "FMP",
    "SDL", "AAA", "NBFC", "CRISIL", "IBX", "HDFC", "REIT", "REITS", "INVIT", "EV", "USD",
    "MSCI", "EAFE", "NYSE", "FANG", "CPSE", "PSE", "G-SEC", "TRI", "II", "III", "IV",
    "BFSI", "FMCG", "AI", "QQQ", "S&P", "NASDAQ",
}
_SMALL = {"and", "of", "to", "the", "in", "for", "or"}


def _titlecase(name: str) -> str:
    words = []
    for i, w in enumerate(name.split(" ")):
        if w.upper() in _ACRONYMS:
            words.append("Nasdaq" if w.upper() == "NASDAQ" else w.upper())
        elif i and w.lower() in _SMALL:
            words.append(w.lower())
        else:
            words.append("-".join(p[:1].upper() + p[1:].lower() for p in w.split("-")))
    return " ".join(words)


def split_title(raw: str) -> tuple[str, str | None]:
    """Split "X Fund (An open ended ...)" into the scheme name and its descriptor."""
    raw = _text(raw)
    descriptor = None
    d = _DESCRIPTOR.search(raw)
    if d:
        descriptor = raw[d.start():].strip()
        if descriptor.startswith("(") and descriptor.endswith(")") and descriptor.count("(") == descriptor.count(")"):
            descriptor = descriptor[1:-1].strip()
        elif descriptor.startswith("(") and descriptor.count("(") > descriptor.count(")"):
            descriptor = descriptor[1:].strip()
    m = _CUT.search(raw)
    name = raw[: m.start()] if m else raw
    name = name.strip(" -–#*^$@")
    if name.isupper():
        name = _titlecase(name)
    return name, descriptor


def slugify(name: str) -> str:
    s = name.lower().replace("&", " and ").replace("'", "").replace("’", "")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
_MONTHS["sept"] = 9


def month_end(month: str) -> date:
    y, m = (int(x) for x in month.split("-"))
    return date(y, m, calendar.monthrange(y, m)[1])


def find_as_of(preamble: Preamble) -> date | None:
    """Find the statement date in the title rows, in any of the formats AMCs use."""
    for row in preamble:
        for t in _row_texts(row):
            if not re.search(r"as on|ended|as at", t, re.I):
                continue
            m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?[-/ ]+([A-Za-z]{3,9})[-/ ,]+(\d{4})", t)
            if m and m.group(2).lower() in _MONTHS:
                return _safe_date(int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1)))
            m = re.search(r"([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", t)
            if m and m.group(1).lower() in _MONTHS:
                return _safe_date(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2)))
            m = re.search(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", t)
            if m:
                return _safe_date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    return None


def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None
