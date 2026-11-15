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
# Pages that print the nonce, tried in order. The home page and /mutual-fund/ do not.
NONCE_PAGES = [PAGE, "https://navi.com/mutual-fund/downloads/"]
DOCS ="https://navi.com/wp-json/nv/v1/documents"
MONTHLY_CATEGORY = "884"
_NONCE = re.compile(r"navi_property\s*=\s*\{[^}]*?\"nonce\"\s*:\s*\"([a-f0-9]+)\"")


def financial_year(year: int, month: int) -> str:
    """Indian financial year label: October 2026 -> '2026-2027', February 2027 -> '2026-2027'."""
    start = year if month >= 4 else year - 1
    return f"{start}-{start + 1}"


def _find_nonce(client, pacer: Pacer, report: FetchReport) -> re.Match:
    """Read the nonce from the first NONCE_PAGES entry that serves it.

    Cloudflare may refuse one path (or a datacenter IP) and not another, so a
    non-200 or a page without the nonce moves on to the next. Each attempt is
    logged with the headers that show whether Cloudflare was the one refusing.
    """
    problems: list[str] = []
    for url in NONCE_PAGES:
        pacer.wait()
        page = client.get(url)
        h = page.headers
        diag = (
            f"{url} -> HTTP {page.status_code} "
            f"(server={h.get('server')}, cf-mitigated={h.get('cf-mitigated')}, "
            f"cf-ray={h.get('cf-ray')})"
        )
        print(f"[navi] nonce page {diag}")
        if page.status_code != 200:
            problems.append(diag)
            continue
        nonce = _NONCE.search(page.text)
        if nonce:
            return nonce
        problems.append(f"{url} -> HTTP 200 but no navi_property.nonce")
    raise FetchError("Navi nonce unavailable: " + "; ".join(problems))


def fetch(month: str, dest: Path) -> FetchReport:
    year, m, month_name = month_parts(month)
    report = FetchReport("navi")
    pacer = Pacer()
    with make_client() as client:
        nonce = _find_nonce(client, pacer, report)
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
