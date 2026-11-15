"""Motilal Oswal: an open JSON endpoint lists every month-end document."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote

from ..http import FetchError, Pacer, download, make_client, safe_filename
from . import FetchReport, month_parts

BASE = "https://www.motilaloswalmf.com"
LIST_URL = (
    f"{BASE}/content/aem-cloud-dept-backend-motilal-oswal/api/search-documents.json"
    "?year=&category=month%20end%20portfolio&month=&type=mf"
)
REFERER = f"{BASE}/downloads/scheme-portfolio-details"


def fetch(month: str, dest: Path) -> FetchReport:
    year, _, month_name = month_parts(month)
    report = FetchReport("motilal")
    pacer = Pacer()
    wanted = re.compile(rf"scheme\s+portfolio\s+details\W+{month_name}\W+{year}\b", re.I)
    api_headers = {"Accept": "*/*", "Referer": REFERER, "Sec-Fetch-Dest": "empty",
                   "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-origin"}
    with make_client() as client:
        pacer.wait()
        resp = client.get(LIST_URL, headers=api_headers)
        if resp.status_code != 200:
            raise FetchError(f"Motilal document list returned HTTP {resp.status_code}")
        docs = [
            d for d in resp.json().get("results", [])
            if wanted.search(d.get("title", "")) or wanted.search(d.get("path", ""))
        ]
        docs = [d for d in docs if d.get("path", "").lower().endswith((".xlsx", ".xls"))]
        if not docs:
            raise FetchError(f"Motilal list has no 'Scheme Portfolio Details {month_name} {year}' document")
        report.listed = len(docs)
        for d in docs:
            url = BASE + quote(d["path"])
            if download(client, url, dest / safe_filename(url), pacer, headers={"Referer": REFERER}):
                report.downloaded += 1
            else:
                report.skipped += 1
    return report
