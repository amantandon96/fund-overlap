"""Turn the raw workbooks in raw/<amc>/<month>/ into the static data/ tree."""

from __future__ import annotations

import json
import shutil
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl

from .adapters import ADAPTERS, Adapter, find_as_of, month_end, slugify, split_title
from .parser import Holding, parse_rows

EQUITY_PCT_LIMIT = 101.0


@dataclass
class Scheme:
    id: str
    name: str
    amc: str
    as_of: str
    descriptor: str | None
    holdings: list[Holding]
    source: str  # "<file> [<sheet>]", for messages only

    @property
    def equity_pct(self) -> float:
        return sum(h.weight for h in self.holdings)


@dataclass
class AmcResult:
    amc: str
    files: int = 0
    sheets: int = 0
    schemes: list[Scheme] = field(default_factory=list)
    no_equity: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _workbook_files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in (".xlsx", ".xls", ".xlsm"))


def parse_amc(adapter: Adapter, folder: Path, month: str) -> AmcResult:
    res = AmcResult(adapter.amc)
    fallback_date = month_end(month)
    seen_ids: dict[str, str] = {}

    for path in _workbook_files(folder):
        if not zipfile.is_zipfile(path):
            res.warnings.append(f"{path.name}: not an xlsx workbook (legacy .xls?), skipped")
            continue
        res.files += 1
        # Some AMCs name xlsx files ".xls"; opening by handle skips openpyxl's extension check.
        with open(path, "rb") as fh:
            wb = openpyxl.load_workbook(fh, read_only=True, data_only=True)
            for ws in wb.worksheets:
                if ws.title.strip().lower() in adapter.skip_sheets:
                    continue
                ws.reset_dimensions()
                parsed = parse_rows(ws.iter_rows(values_only=True), adapter.default_unit, adapter.multi_equity)
                if not parsed.header_found:
                    continue
                res.sheets += 1
                source = f"{path.name} [{ws.title}]"
                name, descriptor = split_title(adapter.title(parsed.preamble))
                if not name:
                    name = ws.title
                    res.warnings.append(f"{source}: no scheme title found, using sheet name")

                if not parsed.holdings:
                    if parsed.unparsed_equity_rows:
                        res.warnings.append(
                            f"{name}: header found but zero holdings parsed "
                            f"({parsed.unparsed_equity_rows} weighted equity rows had no valid ISIN) - {source}"
                        )
                    else:
                        res.no_equity.append(name)
                    continue

                as_of = find_as_of(parsed.preamble)
                if as_of is None:
                    as_of = fallback_date
                elif (as_of.year, as_of.month) != (fallback_date.year, fallback_date.month):
                    res.warnings.append(f"{name}: statement date {as_of} is outside {month} - {source}")

                sid = slugify(name)
                if not sid.startswith(adapter.amc):
                    sid = f"{adapter.amc}-{sid}"
                if sid in seen_ids:
                    sid = f"{sid}-{slugify(ws.title)}"
                    res.warnings.append(f"{name}: duplicate scheme name, id disambiguated as {sid} - {source}")
                seen_ids[sid] = source

                scheme = Scheme(sid, name, adapter.amc, as_of.isoformat(), descriptor, parsed.holdings, source)
                if parsed.unit == "unknown":
                    res.warnings.append(f"{name}: could not tell percent from fraction - {source}")
                if scheme.equity_pct > EQUITY_PCT_LIMIT:
                    res.warnings.append(
                        f"{name}: equity weights sum to {scheme.equity_pct:.2f}% (>101) - {source}"
                    )
                res.schemes.append(scheme)
            wb.close()
    return res


def _pick(counter: Counter) -> str:
    """Most common spelling, ignoring case; prefer mixed case over ALL CAPS."""
    by_key: dict[str, Counter] = defaultdict(Counter)
    for value, n in counter.items():
        if value:
            by_key[value.lower()][value] += n
    if not by_key:
        return ""
    key = max(by_key, key=lambda k: (sum(by_key[k].values()), k))
    variants = by_key[key]
    return max(variants, key=lambda v: (not v.isupper(), variants[v], v))


def build(root: Path, month: str, amcs: list[str] | None = None) -> list[AmcResult]:
    raw_root, data_root = root / "raw", root / "data"
    results: list[AmcResult] = []
    for amc in amcs or list(ADAPTERS):
        folder = raw_root / amc / month
        if not folder.is_dir() or not _workbook_files(folder):
            res = AmcResult(amc)
            res.warnings.append(f"no raw files in {folder.relative_to(root)}; existing data for this AMC left as is")
            results.append(res)
            continue
        results.append(parse_amc(ADAPTERS[amc], folder, month))

    rebuilt = {r.amc for r in results if r.schemes}

    # Keep what earlier builds produced for AMCs that were not rebuilt this time.
    index_path, sec_path = data_root / "index.json", data_root / "securities.json"
    old_index = json.loads(index_path.read_text()) if index_path.exists() else []
    securities = json.loads(sec_path.read_text()) if sec_path.exists() else {}
    entries = [e for e in old_index if e.get("amc") not in rebuilt]

    names: dict[str, Counter] = defaultdict(Counter)
    sectors: dict[str, Counter] = defaultdict(Counter)
    for res in results:
        if not res.schemes:
            continue
        out_dir = data_root / "holdings" / res.amc
        if out_dir.exists():
            shutil.rmtree(out_dir)
        out_dir.mkdir(parents=True)
        for s in res.schemes:
            rows = [[h.isin, round(h.weight, 4)] for h in s.holdings]
            (out_dir / f"{s.id}.json").write_text(json.dumps(rows, separators=(",", ":")))
            entry = {
                "id": s.id,
                "name": s.name,
                "amc": s.amc,
                "as_of": s.as_of,
                "equity_pct": round(s.equity_pct, 2),
                "holdings": len(s.holdings),
            }
            if s.descriptor:
                entry["descriptor"] = s.descriptor
            entries.append(entry)
            for h in s.holdings:
                names[h.isin][h.name] += 1
                sectors[h.isin][h.industry] += 1

    # Canonical names are a vote across every scheme. Only a build of all AMCs
    # has the full electorate, so a partial build just adds ISINs it has not seen.
    full_build = rebuilt == set(ADAPTERS)
    if full_build:
        securities = {}
    for isin in names:
        if full_build or isin not in securities:
            securities[isin] = {"name": _pick(names[isin]), "sector": _pick(sectors[isin])}

    entries.sort(key=lambda e: (e["amc"], e["name"].lower()))
    data_root.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(entries, ensure_ascii=False, indent=1) + "\n")
    sec_path.write_text(
        json.dumps(dict(sorted(securities.items())), ensure_ascii=False, separators=(",", ":")) + "\n"
    )
    return results


def print_summary(results: list[AmcResult]) -> None:
    print(f"{'AMC':<10}{'files':>6}{'sheets':>8}{'schemes':>9}{'no equity':>11}{'holdings':>10}{'warnings':>10}")
    for r in results:
        print(
            f"{r.amc:<10}{r.files:>6}{r.sheets:>8}{len(r.schemes):>9}{len(r.no_equity):>11}"
            f"{sum(len(s.holdings) for s in r.schemes):>10}{len(r.warnings):>10}"
        )
    print(
        f"{'total':<10}{sum(r.files for r in results):>6}{sum(r.sheets for r in results):>8}"
        f"{sum(len(r.schemes) for r in results):>9}{sum(len(r.no_equity) for r in results):>11}"
        f"{sum(len(s.holdings) for r in results for s in r.schemes):>10}"
        f"{sum(len(r.warnings) for r in results):>10}"
    )
    for r in results:
        for w in r.warnings:
            print(f"WARNING [{r.amc}] {w}")
