"""Shared parser for one scheme sheet of an AMC monthly portfolio workbook.

Every AMC lays a scheme out the same way: some title rows, a header row that
contains an "ISIN" column, then sections ("Equity & Equity related", "Debt
Instruments", ...) each closed by a "Total" row, and finally a "Grand Total".
The parser works on plain row tuples so it can be tested without files.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Sequence

ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")

_EQUITY_START = re.compile(r"^(\([a-z]\)\s*)?equity\s*(&|and)\s*equity\s*related", re.I)
# Backstop for sheets that do not close the equity section with a "Total" row.
_SECTION_END = re.compile(
    r"^(\([a-z]\)\s*)?("
    r"debt instruments?|money market instruments?|others?|grand total|"
    r"net current assets|net receivables|treps|reverse repo|"
    r"units issued by invit|invit|government securities|"
    r"exchange traded funds?|mutual fund units?|derivatives?|"
    r"foreign securities and\s*/?\s*or overseas etf"
    r")\b",
    re.I,
)
_GRAND_TOTAL = re.compile(r"^grand\s+total\b", re.I)
_TOTAL = re.compile(r"^total$", re.I)
_SUBTOTAL = re.compile(r"^sub\s*-?\s*total$", re.I)

# Footnote marks AMCs append to instrument names, e.g. "HDFC Bank Ltd.£".
_MARKS = "£*#$@^~+†‡§"
_HEADER_SCAN_LIMIT = 60


@dataclass
class Holding:
    isin: str
    name: str
    industry: str
    weight: float  # percent of net assets


@dataclass
class ParsedSheet:
    header_found: bool = False
    equity_section_found: bool = False
    holdings: list[Holding] = field(default_factory=list)
    unit: str = "unknown"  # "percent", "fraction" or "unknown"
    grand_total: float | None = None
    preamble: list[tuple] = field(default_factory=list)  # rows above the header
    unparsed_equity_rows: int = 0  # weighted rows in the equity section with no valid ISIN
    tiny_rows: int = 0  # ISIN rows whose weight was a mark such as "$" (below 0.01%)

    @property
    def equity_pct(self) -> float:
        return sum(h.weight for h in self.holdings)


def _text(cell) -> str:
    if cell is None:
        return ""
    return re.sub(r"\s+", " ", str(cell)).strip()


def _number(cell) -> float | None:
    if isinstance(cell, bool):
        return None
    if isinstance(cell, (int, float)):
        return float(cell)
    if isinstance(cell, str):
        s = cell.strip().replace(",", "").rstrip("%")
        try:
            return float(s)
        except ValueError:
            return None
    return None


def clean_name(raw) -> str:
    """Strip footnote marks and stray whitespace from an instrument name."""
    name = _text(raw)
    name = name.strip(_MARKS + " ")
    return re.sub(r"\s+", " ", name)


def _find_columns(row: Sequence) -> dict[str, int] | None:
    cells = [_text(c).lower() for c in row]
    if "isin" not in cells:
        return None
    cols = {"isin": cells.index("isin")}
    for i, c in enumerate(cells):
        if "name" not in cols and re.search(r"name of (the )?instrument", c):
            cols["name"] = i
        elif "weight" not in cols and re.search(r"%\s*to\s*(nav|net\s*assets?)", c):
            cols["weight"] = i
        elif "industry" not in cols and "industry" in c:
            cols["industry"] = i
    if "industry" not in cols:
        for i, c in enumerate(cells):
            if re.search(r"rating|sector", c):
                cols["industry"] = i
                break
    if "name" not in cols or "weight" not in cols:
        return None
    return cols


def _cell(row: Sequence, idx: int | None):
    if idx is None or idx >= len(row):
        return None
    return row[idx]


def parse_rows(
    rows: Iterable[Sequence], default_unit: str | None = None, multi_equity: bool = False
) -> ParsedSheet:
    """Parse the rows of one scheme sheet.

    ``default_unit`` ("percent" or "fraction") is only used when the sheet has
    no usable Grand Total row to tell the two conventions apart.

    ``multi_equity`` is for AMCs that list overseas stocks under a second
    "Equity & Equity related ..." heading after the first section's Total row.
    Without it, everything after that first Total is ignored.
    """
    out = ParsedSheet()
    cols: dict[str, int] | None = None
    state = "before"  # before -> equity -> after
    raw: list[tuple[str, str, str, float]] = []

    for n, row in enumerate(rows):
        if cols is None:
            cols = _find_columns(row)
            if cols is None:
                out.preamble.append(tuple(row))
                if n >= _HEADER_SCAN_LIMIT:
                    return out
                continue
            out.header_found = True
            continue

        isin = _text(_cell(row, cols["isin"])).upper()
        weight = _number(_cell(row, cols["weight"]))
        labels = [t for t in (_text(c) for c in row[: cols["weight"]]) if t]

        if any(_GRAND_TOTAL.match(t) for t in labels):
            if weight is not None:
                out.grand_total = weight
            break

        if state == "before":
            if any(_EQUITY_START.match(t) for t in labels):
                state = "equity"
                out.equity_section_found = True
            continue
        if state == "after":
            if multi_equity and any(_EQUITY_START.match(t) for t in labels):
                state = "equity"
            continue

        # state == "equity"
        if ISIN_RE.match(isin):
            if weight is None:
                out.tiny_rows += 1
                continue
            raw.append(
                (
                    isin,
                    clean_name(_cell(row, cols["name"])),
                    _text(_cell(row, cols.get("industry"))),
                    weight,
                )
            )
            continue
        if any(_TOTAL.match(t) or _SECTION_END.match(t) for t in labels):
            state = "after"
            continue
        if weight is not None and weight > 0 and not any(_SUBTOTAL.match(t) for t in labels):
            out.unparsed_equity_rows += 1

    out.unit = _decide_unit(out.grand_total, raw, default_unit)
    scale = 100.0 if out.unit == "fraction" else 1.0

    merged: dict[str, Holding] = {}
    for isin, name, industry, weight in raw:
        w = weight * scale
        if isin in merged:
            merged[isin].weight += w
        else:
            merged[isin] = Holding(isin, name, industry, w)
    out.holdings = sorted(
        (h for h in merged.values() if h.weight > 0), key=lambda h: (-h.weight, h.isin)
    )
    return out


def _decide_unit(grand_total, raw, default_unit) -> str:
    """Fractions total about 1, percentages about 100; the sheet tells us which."""
    if grand_total is not None:
        if 0.5 <= grand_total <= 1.5:
            return "fraction"
        if 50 <= grand_total <= 150:
            return "percent"
    if default_unit in ("percent", "fraction"):
        return default_unit
    if not raw:
        return "unknown"
    total = sum(w for *_, w in raw)
    # No stated total and no hint: an equity sleeve summing to <= 1.5 can only
    # be fractions unless the fund is almost entirely non-equity.
    return "fraction" if total <= 1.5 else "percent"
