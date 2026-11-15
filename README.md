# fund-overlap

Measures how much a set of Indian mutual funds overlap in the stocks they hold.

## Data pipeline

`pipeline/` downloads each AMC's monthly portfolio disclosure and turns it into
small static JSON files under `data/`. It needs [uv](https://docs.astral.sh/uv/).

```sh
cd pipeline

# Download October 2026 files into raw/<amc>/2026-10/, then rebuild data/
uv run fund-overlap refresh --month 2026-10

# Or run the two steps separately, optionally for one AMC
uv run fund-overlap fetch --month 2026-10 --amc hdfc
uv run fund-overlap build --month 2026-10

# Tests
uv run pytest
```

`refresh` without `--month` uses the previous calendar month. AMCs publish a
month's portfolio within about ten days of month end.

Supported AMCs: `nippon`, `hdfc`, `axis`, `motilal`, `navi`, `ppfas` (Parag Parikh).

### What goes where

| Path | Contents | In git |
|---|---|---|
| `raw/<amc>/<YYYY-MM>/` | Spreadsheets exactly as downloaded | No |
| `data/index.json` | One entry per scheme with equity holdings: `id`, `name`, `amc`, `as_of`, `equity_pct`, `holdings` (count), optional `descriptor` | Yes |
| `data/securities.json` | `ISIN -> {name, sector}` | Yes |
| `data/holdings/<amc>/<id>.json` | `[[isin, weight_percent], ...]`, largest first | Yes |

Only the "Equity & Equity related" section of each scheme is kept. Debt, cash,
derivatives and fund-of-fund units are left out, so `equity_pct` is usually
below 100. Schemes with no equity holdings do not appear in the index.

`build` replaces the data of every AMC that has raw files for the month and
leaves other AMCs' existing data alone.

### Fetching notes

- Files already in `raw/` are not downloaded again.
- Requests are spaced out: 4-5 seconds apart for HDFC, about 2 seconds elsewhere.
  A full HDFC pull is about 110 files and takes roughly nine minutes.
- If a site blocks the fetcher, download the month's spreadsheets by hand into
  `raw/<amc>/<YYYY-MM>/` and run `build`. The parsers only read local files.
- Parag Parikh publishes one combined workbook per month plus the same schemes again as separate files. Only the combined workbook is fetched, so no scheme is counted twice. Its Flexi Cap sheet lists overseas stocks under a second equity heading, which the `ppfas` adapter includes (`multi_equity`).
- HDFC's page embeds only the latest month, so older HDFC months need a manual download.
- Axis's list API uses a token that is hardcoded in the site's public scripts.
  If it changes, the fetcher re-reads it and prints the new value to store in
  `pipeline/src/fund_overlap/fetchers/axis.py`.

### Build warnings

`build` prints a per-AMC summary and warns when a scheme's equity weights sum
to more than 101%, when a sheet has an equity section but no row could be
parsed, or when a statement date falls outside the requested month.

## Web app

The app in `web/` is a static site (TypeScript, built with Vite). It reads the files in `data/` and does all calculation in the browser.

```sh
cd web
npm install
npm run dev      # copies ../data into public/data, then serves with live reload
npm test         # overlap, search and file-format tests
npm run build    # type-checks and writes the deployable site to web/dist
```

- **Colours and fonts** are defined only in `web/src/theme.css`, one line per colour as a light and dark pair.
- **Heatmap scale:** `HEAT_MAX` in `web/src/main.ts` is the overlap percentage that gets the strongest colour.
- **Search cut-off:** funds with less than `MIN_EQUITY_PCT` equity (also in `main.ts`) are left out of search.
- **Theming is behind a flag and off by default.** The app is light only: the theme switcher is not shown, and `?theme=` and any saved choice are ignored. Set `VITE_ENABLE_THEMING=true` when running or building (`VITE_ENABLE_THEMING=true npm run dev`) to get the System / Light / Dark switcher back. With it on, `?theme=dark` or `?theme=light` forces a theme for that visit.

`mockup/index.html` is the original static design mock, kept for reference.
