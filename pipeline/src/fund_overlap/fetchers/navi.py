"""Navi: per-scheme files, listed by a WordPress endpoint that wants the page's nonce.

The nonce is printed into the public portfolio page for every visitor, so it is
read fresh on each run.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

from ..http import FetchError, Pacer, download, make_client, safe_filename
from . import FetchReport, month_parts

PAGE = "https://navi.com/mutual-fund/downloads/portfolio/"
DOCS = "https://navi.com/wp-json/nv/v1/documents"
MONTHLY_CATEGORY = "884"
_NONCE = re.compile(r"navi_property\s*=\s*\{[^}]*?\"nonce\"\s*:\s*\"([a-f0-9]+)\"")


def financial_year(year: int, month: int) -> str:
    """Indian financial year label: October 2026 -> '2026-2027', February 2027 -> '2026-2027'."""
    start = year if month >= 4 else year - 1
    return f"{start}-{start + 1}"


def fetch(month: str, dest: Path) -> FetchReport:
    year, m, month_name = month_parts(month)
    report = FetchReport("navi")
    pacer = Pacer()
    with make_client() as client:
        pacer.wait()
        page = client.get(PAGE)
        if page.status_code != 200:
            raise FetchError(f"Navi portfolio page returned HTTP {page.status_code}")
        nonce = _NONCE.search(page.text)
        if not nonce:
            raise FetchError("Navi portfolio page no longer exposes navi_property.nonce")
        pacer.wait()
        resp = client.post(
            DOCS,
            data={
                "financial_year": financial_year(year, m),
                "value": month_name,
                "category": MONTHLY_CATEGORY,
                "type": "Monthly",
                "order": "DESC",
            },
            headers={
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "WP-NONCE": nonce.group(1),
                "X-Requested-With": "XMLHttpRequest",
                "Origin": "https://navi.com",
                "Referer": PAGE,
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-origin",
            },
        )
        if resp.status_code != 200:
            raise FetchError(f"Navi documents endpoint returned HTTP {resp.status_code}")
        body = resp.json()
        docs = body.get("data") or []
        urls: list[str] = []
        for d in docs:
            title = html.unescape(d.get("title", ""))
            if month_name.lower() not in title.lower() or str(year) not in title:
                report.notes.append(f"ignored listing for another period: {title}")
                continue
            u = d.get("url")
            urls.extend(u if isinstance(u, list) else [u])
        urls = [u for u in urls if u and u.lower().split("?")[0].endswith((".xlsx", ".xls"))]
        if not urls:
            raise FetchError(f"Navi lists no monthly portfolio files for {month_name} {year}")
        report.listed = len(urls)
        for url in urls:
            if download(client, url, dest / safe_filename(url), pacer):
                report.downloaded += 1
            else:
                report.skipped += 1
    return report
