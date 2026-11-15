"""Small HTTP helpers shared by the fetchers: browser-like headers, pacing, downloads."""

from __future__ import annotations

import random
import re
import time
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36"
)

# What Chrome sends on a top-level page navigation. HDFC's bot filter rejects
# requests that carry only a User-Agent.
NAVIGATION_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Upgrade-Insecure-Requests": "1",
    "sec-ch-ua": '"Not-A.Brand";v="99", "Google Chrome";v="157", "Chromium";v="157"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}


class FetchError(RuntimeError):
    pass


class Pacer:
    """Sleeps so that consecutive requests are at least lo..hi seconds apart."""

    def __init__(self, lo: float = 1.5, hi: float = 2.5):
        self.lo, self.hi = lo, hi
        self._last = 0.0

    def wait(self) -> None:
        gap = random.uniform(self.lo, self.hi) - (time.monotonic() - self._last)
        if self._last and gap > 0:
            time.sleep(gap)
        self._last = time.monotonic()


def make_client(http2: bool = True) -> httpx.Client:
    return httpx.Client(
        http2=http2,
        headers=NAVIGATION_HEADERS,
        follow_redirects=True,
        timeout=httpx.Timeout(90.0, connect=30.0),
    )


def safe_filename(url: str) -> str:
    name = unquote(Path(urlsplit(url).path).name)
    return re.sub(r"[^A-Za-z0-9._ &()-]+", "_", name).strip() or "download.xlsx"


def download(client: httpx.Client, url: str, dest: Path, pacer: Pacer, headers: dict | None = None) -> bool:
    """Download url to dest unless it is already there. Returns True if fetched."""
    if dest.exists() and dest.stat().st_size > 0:
        return False
    pacer.wait()
    resp = client.get(url, headers=headers)
    if resp.status_code != 200:
        raise FetchError(f"GET {url} returned HTTP {resp.status_code}")
    tmp = dest.with_name(dest.name + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_bytes(resp.content)
    if not zipfile.is_zipfile(tmp):
        tmp.unlink()
        raise FetchError(f"{url} did not return an xlsx workbook ({len(resp.content)} bytes)")
    tmp.replace(dest)
    return True
