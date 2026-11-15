"""Command line entry point: fetch, build, refresh."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

from .adapters import ADAPTERS
from .http import FetchError


def repo_root() -> Path:
    # pipeline/src/fund_overlap/cli.py -> repository root
    return Path(__file__).resolve().parents[3]


def previous_month(today: date | None = None) -> str:
    today = today or date.today()
    y, m = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
    return f"{y:04d}-{m:02d}"


def _month(value: str) -> str:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value):
        raise argparse.ArgumentTypeError("month must look like 2026-10")
    return value


def cmd_fetch(args) -> int:
    from .fetchers import registry

    fetchers = registry()
    failed = 0
    for amc in args.amc or list(fetchers):
        dest = args.root / "raw" / amc / args.month
        print(f"[{amc}] fetching {args.month} -> {dest.relative_to(args.root)}", flush=True)
        try:
            rep = fetchers[amc](args.month, dest)
        except (FetchError, OSError, ValueError) as exc:
            failed += 1
            print(f"[{amc}] FAILED: {exc}", flush=True)
            continue
        except Exception as exc:  # network errors from the HTTP client
            failed += 1
            print(f"[{amc}] FAILED: {type(exc).__name__}: {exc}", flush=True)
            continue
        print(f"[{amc}] listed {rep.listed}, downloaded {rep.downloaded}, already present {rep.skipped}", flush=True)
        for note in rep.notes:
            print(f"[{amc}] note: {note}", flush=True)
    return 1 if failed else 0


def cmd_build(args) -> int:
    from .build import build, print_summary

    results = build(args.root, args.month, args.amc)
    print_summary(results)
    return 0 if any(r.schemes for r in results) else 1


def cmd_refresh(args) -> int:
    fetch_status = cmd_fetch(args)
    build_status = cmd_build(args)
    return fetch_status or build_status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fund-overlap", description=__doc__)
    parser.add_argument("--root", type=Path, default=repo_root(), help="repository root (holds raw/ and data/)")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p, month_required: bool):
        p.add_argument("--month", type=_month, required=month_required,
                       default=None if month_required else previous_month(),
                       help="portfolio month, e.g. 2026-10" + ("" if month_required else " (default: last month)"))
        p.add_argument("--amc", action="append", choices=sorted(ADAPTERS),
                       help="limit to one AMC; repeat for several (default: all)")

    p = sub.add_parser("fetch", help="download the month's portfolio files into raw/")
    common(p, True)
    p.set_defaults(func=cmd_fetch)
    p = sub.add_parser("build", help="parse raw/ and write data/")
    common(p, True)
    p.set_defaults(func=cmd_build)
    p = sub.add_parser("refresh", help="fetch, then build")
    common(p, False)
    p.set_defaults(func=cmd_refresh)

    args = parser.parse_args(argv)
    args.root = args.root.resolve()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
