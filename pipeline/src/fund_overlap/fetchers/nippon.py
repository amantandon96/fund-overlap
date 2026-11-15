"""Nippon India: one workbook for all schemes, linked from a public listing page.

The filename's date part is not consistent month to month ("31-Oct-26",
"30-April-26", "31-July-26"), so the link is discovered rather than constructed.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..http import FetchError, Pacer, download, make_client, safe_filename
from . import FetchReport, month_parts

BASE = "https://mf.nipponindiaim.com"
LISTING = f"{BASE}/investor-service/downloads/factsheet-portfolio-and-other-disclosures"
_LINK = re.compile(
    r"/InvestorServices/FactsheetsDocuments/[^\"'<> ]*MONTHLY[-_ ]PORTFOLIO[-_ ](\d{1,2})[-_ ]([A-Za-z]+)[-_ ](\d{2,4})\.xlsx?",
    re.I,
)


def fetch(month: str, dest: Path) -> FetchReport:
    year, _, month_name = month_parts(month)
    report = FetchReport("nippon")
    pacer = Pacer()
    with make_client() as client:
        pacer.wait()
        resp = client.get(LISTING)
        if resp.status_code != 200:
            raise FetchError(f"Nippon listing page returned HTTP {resp.status_code}")
        matches = []
        for m in _LINK.finditer(resp.text):
            link_year = int(m.group(3)) % 100
            if m.group(2)[:3].lower() == month_name[:3].lower() and link_year == year % 100:
                matches.append(m.group(0))
        matches = sorted(set(matches))
        if not matches:
            raise FetchError(f"Nippon listing page has no monthly portfolio link for {month_name} {year}")
        report.listed = len(matches)
        for link in matches:
            url = BASE + link
            if download(client, url, dest / safe_filename(url), pacer):
                report.downloaded += 1
            else:
                report.skipped += 1
    return report
