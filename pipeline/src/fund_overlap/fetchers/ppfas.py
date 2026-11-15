"""Parag Parikh (PPFAS): a static page links every month's files directly.

Each month has one combined workbook (one sheet per scheme, named
``PPFAS_Monthly_Portfolio_Report_<Month>_<day>_<year>.xls``, though it is really
xlsx) plus the same schemes again as separate ``<CODE>_PPFAS_...`` files. Only
the combined workbook is fetched, because building from both would list every
scheme twice. The per-scheme files are a fallback if the combined one is missing.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

from ..http import FetchError, Pacer, download, make_client, safe_filename
from . import FetchReport, month_parts

BASE = "https://amc.ppfas.com"
PAGE = f"{BASE}/downloads/portfolio-disclosure/"
_HREF = re.compile(r'href="([^"]+\.xlsx?)(?:\?[^"]*)?"', re.I)


def _links(page: str, month_name: str, year: int) -> list[str]:
    period = re.compile(rf"PPFAS_Monthly_Portfolio_Report_{month_name}_\d{{1,2}}_{year}\.xlsx?$", re.I)
    return [html.unescape(h) for h in _HREF.findall(page) if period.search(h)]


def fetch(month: str, dest: Path) -> FetchReport:
    year, _, month_name = month_parts(month)
    report = FetchReport("ppfas")
    pacer = Pacer()
    with make_client() as client:
        pacer.wait()
        page = client.get(PAGE)
        if page.status_code != 200:
            raise FetchError(f"PPFAS portfolio page returned HTTP {page.status_code}")
        links = _links(page.text, month_name, year)
        combined = [h for h in links if h.rsplit("/", 1)[-1].upper().startswith("PPFAS_")]
        chosen = combined or links
        if not chosen:
            raise FetchError(f"PPFAS lists no monthly portfolio files for {month_name} {year}")
        if not combined:
            report.notes.append("combined workbook not listed; using the per-scheme files")
        report.listed = len(chosen)
        for href in dict.fromkeys(chosen):
            url = href if href.startswith("http") else BASE + href
            if download(client, url, dest / safe_filename(url), pacer):
                report.downloaded += 1
            else:
                report.skipped += 1
    return report
