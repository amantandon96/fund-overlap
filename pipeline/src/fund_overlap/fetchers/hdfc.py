"""HDFC: one file per scheme, embedded as JSON in the monthly-portfolio page.

The site's bot filter needs a full set of Chrome navigation headers over
HTTP/2 and the cookies set by the homepage. Requests are spaced 4-5 seconds.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..http import FetchError, Pacer, download, make_client, safe_filename
from . import FetchReport, month_parts

HOME = "https://www.hdfcfund.com/"
LISTING = "https://www.hdfcfund.com/statutory-disclosure/portfolio/monthly-portfolio"
_FILE = re.compile(r'"filename"\s*:\s*("(?:[^"\\]|\\.)*")\s*,\s*"url"\s*:\s*("(?:[^"\\]|\\.)*")')


def fetch(month: str, dest: Path) -> FetchReport:
    year, _, month_name = month_parts(month)
    report = FetchReport("hdfc")
    pacer = Pacer(4.0, 5.0)
    with make_client(http2=True) as client:
        pacer.wait()
        home = client.get(HOME)
        if home.status_code != 200:
            raise FetchError(f"HDFC homepage returned HTTP {home.status_code} (bot filter?)")
        pacer.wait()
        page = client.get(LISTING, headers={"Referer": HOME, "Sec-Fetch-Site": "same-origin"})
        if page.status_code != 200:
            raise FetchError(f"HDFC monthly portfolio page returned HTTP {page.status_code} (bot filter?)")

        files: dict[str, str] = {}
        other_periods = 0
        wanted = re.compile(rf"\b{month_name}\s+{year}\b", re.I)
        for m in _FILE.finditer(page.text):
            filename, url = json.loads(m.group(1)), json.loads(m.group(2))
            if not filename.lower().endswith((".xlsx", ".xls")) or "monthly" not in filename.lower():
                continue
            if wanted.search(filename):
                files[filename] = url
            else:
                other_periods += 1
        if other_periods:
            report.notes.append(f"{other_periods} listed files are for other periods and were ignored")
        if not files:
            raise FetchError(
                f"HDFC page lists no monthly files for {month_name} {year}; "
                "it embeds only the latest month, so older months need a manual download"
            )
        report.listed = len(files)
        file_headers = {"Referer": HOME, "Sec-Fetch-Site": "same-site"}
        for filename, url in sorted(files.items()):
            if download(client, url, dest / safe_filename(filename), pacer, headers=file_headers):
                report.downloaded += 1
            else:
                report.skipped += 1
    return report
