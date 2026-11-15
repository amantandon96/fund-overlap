"""Axis: one consolidated workbook, listed by a CMS endpoint.

The endpoint needs a bearer token that is hardcoded in the site's public
JavaScript (the same value for every anonymous visitor). If the stored value
stops working, it is re-read from the page's script chunks.
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx

from ..http import FetchError, Pacer, download, make_client, safe_filename
from . import FetchReport, month_parts

BASE = "https://www.axismf.com"
PAGE = f"{BASE}/statutory-disclosures"
DOCS = f"{BASE}/cms/get-scheme-documents"
# Public site-wide value, taken from the site's own script bundle (CMSTOKEN).
DEFAULT_TOKEN = (
    "c060dc4235de5fefc8fe5da8ef2b64d59fdf4f46c8ebeddb394a47daeac8c67c083d602ed9d4133d32b50ce33241fbed"
    "b6240c94cc801279292b3f301ae1ef6f713e38c38d778f9a7ec84bd4c094c0b5fa3cd8b3c5e9d5ae43b9a47ddcfe60b6"
    "339fe8395818d3f21ffaaaca455fe03e48b47a5079bf4a2eb86fece310b253ff"
)
_CHUNK = re.compile(r"/_next/static/chunks/[^\"'\\ ]+\.js")
_TOKEN = re.compile(r"CMSTOKEN\s*:\s*\"Bearer ([a-f0-9]{64,})\"")
_TOKEN_FALLBACK = re.compile(r"Bearer ([a-f0-9]{128,})")


def discover_token(client: httpx.Client, pacer: Pacer) -> str:
    pacer.wait()
    page = client.get(PAGE)
    if page.status_code != 200:
        raise FetchError(f"Axis disclosures page returned HTTP {page.status_code}")
    chunks = sorted(set(_CHUNK.findall(page.text)), key=lambda c: ("layout" not in c, c))
    quick = Pacer(0.3, 0.6)  # static script files on the CDN
    for chunk in chunks:
        quick.wait()
        js = client.get(BASE + chunk, headers={"Accept": "*/*", "Referer": PAGE})
        if js.status_code != 200:
            continue
        m = _TOKEN.search(js.text) or _TOKEN_FALLBACK.search(js.text)
        if m:
            return m.group(1)
    raise FetchError("Axis API token not found in the site's scripts; download the workbook manually")


def _list_documents(client: httpx.Client, token: str, year: int, month_name: str) -> httpx.Response:
    return client.post(
        DOCS,
        json={
            "sdType": "yearMonthSchemeDocs",
            "sdID": "sdMonthSchemePortfolio",
            "year": str(year),
            "month": month_name,
            "schemeCode": "Consolidated",
        },
        headers={
            "Accept": "*/*",
            "Authorization": f"Bearer {token}",
            "Origin": BASE,
            "Referer": PAGE,
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        },
    )


def fetch(month: str, dest: Path) -> FetchReport:
    year, _, month_name = month_parts(month)
    report = FetchReport("axis")
    pacer = Pacer()
    with make_client() as client:
        pacer.wait()
        resp = _list_documents(client, DEFAULT_TOKEN, year, month_name)
        if resp.status_code in (401, 403):
            report.notes.append("stored API token was rejected; re-read it from the site's scripts")
            token = discover_token(client, pacer)
            if token == DEFAULT_TOKEN:
                raise FetchError("Axis API rejects the token its own site publishes (HTTP 403)")
            report.notes.append(f"new token starts {token[:12]}...; update DEFAULT_TOKEN in fetchers/axis.py")
            pacer.wait()
            resp = _list_documents(client, token, year, month_name)
        if resp.status_code != 200:
            raise FetchError(f"Axis document list returned HTTP {resp.status_code}")
        data = resp.json().get("data") or {}
        docs = [
            d for d in data.get("documentList") or []
            if d.get("documentName", "").strip().lower().startswith("monthly portfolio")
            and d.get("docuementURL", "").lower().endswith((".xlsx", ".xls"))
        ]
        if not docs:
            raise FetchError(f"Axis lists no 'Monthly Portfolio' workbook under {month_name} {year}")
        report.listed = len(docs)
        for d in docs:
            url = d["docuementURL"]
            if download(client, url, dest / safe_filename(url), pacer, headers={"Referer": PAGE}):
                report.downloaded += 1
            else:
                report.skipped += 1
    return report
