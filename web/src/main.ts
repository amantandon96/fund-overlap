import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "./theme.css";
import "./styles.css";
import { amcName, loadHoldings, loadIndex, loadSecurities } from "./data";
import { analyse, pairOverlap, type Analysis } from "./overlap";
import { summariseHouses } from "./houses";
import { createSearch } from "./search";
import { downloadFile, loadLocal, parsePortfolioFile, saveLocal, toCsv, type PortfolioFile } from "./storage";
import type { Holding, Scheme, Security } from "./types";

/** Overlap percentage that gets the strongest heatmap colour. */
const HEAT_MAX = 50;
/** Funds with less equity than this are left out of search: comparing them says little. */
const MIN_EQUITY_PCT = 20;
const PAIR_ROWS = 25;
const EXPOSURE_ROWS = 50;

// ---------- small helpers ----------

type Child = Node | string | null | undefined | false;

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attrs: Record<string, string | boolean | undefined> = {},
  ...children: Child[]
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs)) {
    if (value === undefined || value === false) continue;
    node.setAttribute(name, value === true ? "" : value);
  }
  node.append(...children.filter((child): child is Node | string => child != null && child !== false));
  return node;
}

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;

const inr = (n: number) => Math.round(n).toLocaleString("en-IN");
const formatAmount = (n: number) => n.toLocaleString("en-IN", { maximumFractionDigits: 2 });
const pct = (n: number) => (n > 0 && n < 0.05 ? "<0.1%" : `${n.toFixed(1)}%`);
const wholePct = (n: number) => `${Math.round(n)}%`;

/** A, B, … Z, AA, AB, … */
function tagFor(index: number): string {
  let tag = "";
  for (let n = index; n >= 0; n = Math.floor(n / 26) - 1) tag = String.fromCharCode(65 + (n % 26)) + tag;
  return tag;
}

function parseAmount(text: string): number | null {
  const n = Number(text.replace(/[,\s₹]/g, ""));
  return Number.isFinite(n) && n > 0 ? n : null;
}

// ---------- state ----------

interface Row {
  id: string;
  amount: string;
}

interface SnapshotFund {
  scheme: Scheme;
  amount: number;
  tag: string;
  holdings: Holding[];
}

/** The inputs and results of the last analysis; unaffected by later edits to the fund list. */
interface Snapshot {
  key: string;
  funds: SnapshotFund[];
  analysis: Analysis;
  securities: Record<string, Security>;
  pair: [number, number] | null;
  showAllPair: boolean;
  showAllExposure: boolean;
}

let schemes = new Map<string, Scheme>();
let search: ReturnType<typeof createSearch> = () => [];
let rows: Row[] = [];
let snapshot: Snapshot | null = null;
let busy = false;

const searchInput = $<HTMLInputElement>("search");
const resultsList = $<HTMLUListElement>("results");
const analyseBtn = $<HTMLButtonElement>("analyse");
const saveBtn = $<HTMLButtonElement>("save");
const fileInput = $<HTMLInputElement>("file");
const output = $("output");

const persist = () => saveLocal("portfolio", rows);
const rowsKey = () => JSON.stringify(rows.map((row) => [row.id, parseAmount(row.amount)]));

function setMsg(text: string, isError = false): void {
  const msg = $("msg");
  msg.textContent = text;
  msg.hidden = text === "";
  msg.classList.toggle("error", isError);
}

// ---------- fund list ----------

function renderFunds(focusId?: string): void {
  const list = $("funds");
  list.replaceChildren();
  rows.forEach((row, index) => {
    const scheme = schemes.get(row.id)!;
    const input = el("input", {
      type: "text",
      inputmode: "decimal",
      autocomplete: "off",
      placeholder: "Amount",
      "aria-label": `Amount in ${scheme.name}`,
    });
    input.value = row.amount;
    input.addEventListener("input", () => {
      row.amount = input.value;
      persist();
      updateControls();
    });
    input.addEventListener("blur", () => {
      const amount = parseAmount(row.amount);
      if (amount === null) return;
      row.amount = input.value = formatAmount(amount);
      persist();
    });
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !analyseBtn.disabled) analyseBtn.click();
    });

    const remove = el("button", { type: "button", class: "x", "aria-label": `Remove ${scheme.name}` }, "✕");
    remove.addEventListener("click", () => {
      rows.splice(rows.indexOf(row), 1);
      persist();
      renderFunds();
      updateControls();
    });

    list.append(
      el(
        "li",
        {},
        el("span", { class: "tag" }, tagFor(index)),
        el("span", { class: "fname" }, scheme.name),
        el("span", { class: "fmeta" }, `${amcName(scheme.amc)} · ${wholePct(scheme.equity_pct)} equity`),
        el("label", { class: "amt" }, el("span", { "aria-hidden": "true" }, "₹"), input),
        remove,
      ),
    );
    if (row.id === focusId) queueMicrotask(() => input.focus());
  });
  $("empty").hidden = rows.length > 0;
}

function updateControls(): void {
  const ready = rows.length >= 2 && rows.every((row) => parseAmount(row.amount) !== null);
  analyseBtn.disabled = !ready || busy;
  saveBtn.disabled = rows.length === 0;
  $("hint").textContent =
    rows.length === 0
      ? ""
      : rows.length < 2
        ? "Add at least two funds."
        : !ready
          ? "Enter an amount for every fund."
          : "Only the proportions between amounts matter, so rough figures work.";
  const stale = document.getElementById("stale");
  if (stale && snapshot) stale.hidden = snapshot.key === rowsKey();
}

// ---------- search box ----------

let matches: string[] = [];
let active = -1;

function closeResults(): void {
  resultsList.hidden = true;
  searchInput.setAttribute("aria-expanded", "false");
  searchInput.removeAttribute("aria-activedescendant");
}

function drawResults(): void {
  const query = searchInput.value.trim();
  if (query === "") return closeResults();

  resultsList.replaceChildren();
  if (matches.length === 0) {
    resultsList.append(
      el("li", { class: "none", role: "presentation" }, "No funds match. Axis, HDFC, Motilal Oswal, Navi, Nippon India and Parag Parikh are covered."),
    );
  }
  matches.forEach((id, index) => {
    const scheme = schemes.get(id)!;
    const option = el(
      "li",
      { role: "option", id: `opt-${index}`, "aria-selected": String(index === active) },
      el("span", {}, scheme.name),
      el("span", { class: "meta" }, `${amcName(scheme.amc)} · ${wholePct(scheme.equity_pct)} equity`),
    );
    // mousedown, not click, so the choice lands before the input's blur closes the list
    option.addEventListener("mousedown", (event) => {
      event.preventDefault();
      choose(id);
    });
    resultsList.append(option);
  });
  resultsList.hidden = false;
  searchInput.setAttribute("aria-expanded", "true");
  if (active >= 0) {
    searchInput.setAttribute("aria-activedescendant", `opt-${active}`);
    document.getElementById(`opt-${active}`)?.scrollIntoView({ block: "nearest" });
  }
}

function choose(id: string): void {
  rows.push({ id, amount: "" });
  persist();
  searchInput.value = "";
  matches = [];
  closeResults();
  setMsg("");
  renderFunds(id);
  updateControls();
}

searchInput.addEventListener("input", () => {
  matches = search(searchInput.value, 12, new Set(rows.map((row) => row.id)));
  active = matches.length > 0 ? 0 : -1;
  drawResults();
});
searchInput.addEventListener("keydown", (event) => {
  if (event.key === "Escape") return closeResults();
  if (resultsList.hidden || matches.length === 0) return;
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    active = (active + (event.key === "ArrowDown" ? 1 : -1) + matches.length) % matches.length;
    drawResults();
  } else if (event.key === "Enter" && active >= 0) {
    event.preventDefault();
    choose(matches[active]!);
  }
});
searchInput.addEventListener("blur", closeResults);
searchInput.addEventListener("focus", drawResults);

// ---------- analysis ----------

function topPair(matrix: (number | null)[][]): [number, number] | null {
  let best: [number, number] | null = null;
  let bestValue = -1;
  for (let i = 0; i < matrix.length; i++) {
    for (let j = i + 1; j < matrix.length; j++) {
      const value = matrix[i]![j] ?? 0;
      if (value > bestValue) [best, bestValue] = [[i, j], value];
    }
  }
  return best;
}

async function runAnalysis(): Promise<void> {
  busy = true;
  analyseBtn.textContent = "Analysing…";
  updateControls();
  setMsg("");
  try {
    const key = rowsKey();
    const picked = rows.map((row, index) => ({
      scheme: schemes.get(row.id)!,
      amount: parseAmount(row.amount)!,
      tag: tagFor(index),
    }));
    const [securities, holdings] = await Promise.all([
      loadSecurities(),
      Promise.all(picked.map((fund) => loadHoldings(fund.scheme))),
    ]);
    const funds: SnapshotFund[] = picked.map((fund, index) => ({ ...fund, holdings: holdings[index]! }));
    const analysis = analyse(funds);
    snapshot = { key, funds, analysis, securities, pair: topPair(analysis.matrix), showAllPair: false, showAllExposure: false };
    renderOutput();
    output.scrollIntoView({ block: "start" });
  } catch {
    setMsg("Could not load the fund data. Check your connection and try again.", true);
  } finally {
    busy = false;
    analyseBtn.textContent = "Analyse";
    updateControls();
  }
}

// ---------- results ----------

/** Sets the heat colour of a matrix cell or pair chip from an overlap percentage. */
function heat(node: HTMLElement, value: number): void {
  const t = Math.min(value / HEAT_MAX, 1);
  node.classList.add("heat");
  const ink = t > 0.75 ? "k4" : t > 0.6 ? "k3" : t > 0.3 ? "k2" : "";
  if (ink) node.classList.add(ink);
  node.style.setProperty("--t1", String(Math.min(t * 2, 1)));
  node.style.setProperty("--t2", String(Math.max(t * 2 - 1, 0)));
}

/** Most funds the phone heatmap shows before falling back to the ranked list. */
const PHONE_GRID_MAX = 9;

const tag = (text: string, title?: string) => el("span", { class: "tag", title }, text);

/** Rebuilds the whole results area, then restores keyboard focus to the control that triggered it. */
function renderOutput(focusKey?: string): void {
  if (!snapshot) return;
  const s = snapshot;
  const stale = el("div", { class: "stale", id: "stale", role: "status" }, "Your funds or amounts have changed since this analysis. Select Analyse to update it.");
  stale.hidden = s.key === rowsKey();
  output.replaceChildren(stale, summarySection(s), matrixSection(s), pairSection(s), exposureSection(s));
  output.hidden = false;
  if (focusKey) output.querySelector<HTMLElement>(`[data-key="${focusKey}"]`)?.focus({ preventScroll: true });
}

function summarySection(s: Snapshot): HTMLElement {
  const a = s.analysis;
  const stat = (value: string, caption: string) => el("div", { class: "stat" }, el("b", {}, value), el("span", {}, caption));
  return el(
    "section",
    {},
    el("h2", {}, "Summary"),
    el(
      "div",
      { class: "stats" },
      stat(a.uniqueStocks.toLocaleString("en-IN"), `unique stocks across ${s.funds.length} funds`),
      stat(wholePct(a.duplicatedPct), "of your money is in stocks held by 2 or more of your funds"),
      stat(wholePct(a.top10Pct), "of your money is in your 10 largest stocks"),
    ),
    a.equityPct < 99 &&
      el(
        "p",
        { class: "note" },
        `Equity holdings make up ${wholePct(a.equityPct)} of the ₹${formatAmount(a.total)} entered. The rest is debt, cash and other assets, which this tool does not compare.`,
      ),
  );
}

function selectPair(i: number, j: number, focusKey: string): void {
  if (!snapshot) return;
  snapshot.pair = [i, j];
  snapshot.showAllPair = false;
  renderOutput(focusKey);
}

function matrixSection(s: Snapshot): HTMLElement {
  const { funds, analysis } = s;
  const isSelected = (i: number, j: number) =>
    s.pair !== null && ((s.pair[0] === i && s.pair[1] === j) || (s.pair[0] === j && s.pair[1] === i));

  // The matrix is symmetric, so only the lower triangle carries numbers. The diagonal is
  // hatched (a fund against itself) and the mirrored half is a faint ghost, so the grid
  // still reads as a grid. Hovering or focusing a cell highlights its row and column labels.
  const table = el("table", { class: "matrix" });
  const colHeads = funds.map((f) => el("th", { scope: "col" }, tag(f.tag, f.scheme.name)));
  table.append(el("thead", {}, el("tr", {}, el("td", {}), ...colHeads)));
  const body = el("tbody");
  for (let i = 0; i < funds.length; i++) {
    const rowFund = funds[i]!;
    const rowHead = el(
      "th",
      { scope: "row" },
      el("span", {}, tag(rowFund.tag), el("span", { class: "rname", title: rowFund.scheme.name }, rowFund.scheme.name)),
    );
    const tr = el("tr", {}, rowHead);
    for (let j = 0; j < funds.length; j++) {
      if (j >= i) {
        tr.append(el("td", { class: j === i ? "diag" : "ghost", "aria-hidden": "true" }));
        continue;
      }
      const colFund = funds[j]!;
      const value = analysis.matrix[i]![j] ?? 0;
      const key = `cell-${i}-${j}`;
      const label = `${rowFund.scheme.name} and ${colFund.scheme.name}: ${pct(value)} overlap`;
      const button = el("button", { type: "button", "data-key": key, "aria-label": label, title: label }, wholePct(value));
      button.addEventListener("click", () => selectPair(i, j, key));
      const lit = (on: boolean) => {
        rowHead.classList.toggle("hl", on);
        colHeads[j]!.classList.toggle("hl", on);
      };
      for (const [event, on] of [["mouseenter", true], ["focus", true], ["mouseleave", false], ["blur", false]] as const) {
        button.addEventListener(event, () => lit(on));
      }
      const td = el("td", { class: isSelected(i, j) ? "sel" : undefined }, button);
      heat(td, value);
      tr.append(td);
    }
    body.append(tr);
  }
  table.append(body);

  // Ranked list of pairs: shown in place of the matrix on phones when there are many funds.
  const pairs: { i: number; j: number; value: number }[] = [];
  for (let i = 0; i < funds.length; i++) {
    for (let j = i + 1; j < funds.length; j++) pairs.push({ i, j, value: analysis.matrix[i]![j] ?? 0 });
  }
  pairs.sort((x, y) => y.value - x.value);
  const pairList = el("ul", { class: "pairs" });
  for (const { i, j, value } of pairs) {
    const a = funds[i]!;
    const b = funds[j]!;
    const key = `pair-${i}-${j}`;
    const chip = el("span", { class: "pval" }, wholePct(value));
    heat(chip, value);
    const button = el(
      "button",
      { type: "button", "data-key": key },
      el("span", { class: "ptags" }, tag(a.tag), tag(b.tag)),
      el("span", { class: "pnames" }, `${a.scheme.name} × ${b.scheme.name}`),
      chip,
    );
    button.addEventListener("click", () => selectPair(i, j, key));
    pairList.append(el("li", { class: isSelected(i, j) ? "sel" : undefined }, button));
  }

  // Phones show a key (letters are all the axes have room for) and a readout line that
  // names the pair under the finger, since touch has no hover tooltips.
  const key = el("ul", { class: "fundkey" }, ...funds.map((f) => el("li", {}, tag(f.tag), el("span", {}, f.scheme.name))));
  const readoutText = (i: number, j: number) =>
    `${funds[i]!.tag} × ${funds[j]!.tag} · ${funds[i]!.scheme.name} × ${funds[j]!.scheme.name} · ${pct(analysis.matrix[i]![j] ?? 0)}`;
  const readout = el("p", { class: "readout", "aria-hidden": "true" }, s.pair ? readoutText(s.pair[0], s.pair[1]) : "Tap a cell to see the pair");
  table.addEventListener("mouseover", (event) => {
    const cell = (event.target as HTMLElement).closest<HTMLElement>("button[data-key]");
    const m = cell?.dataset.key?.match(/^cell-(\d+)-(\d+)$/);
    if (m) readout.textContent = readoutText(Number(m[1]), Number(m[2]));
  });

  return el(
    "section",
    { class: funds.length > PHONE_GRID_MAX ? "many" : undefined, style: `--n:${funds.length}` },
    el("div", { class: "sec-head" }, el("h2", {}, "Fund-to-fund overlap")),
    el("div", { class: "scroll matrix-wrap" }, table),
    readout,
    key,
    pairList,
    el("div", { class: "legend", "aria-hidden": "true" }, el("span", {}, "0%"), el("i"), el("span", {}, `${HEAT_MAX}% or more`)),
    el("p", { class: "note" }, "Overlap is the share of two funds invested in the same stocks at the same weights. Select a pair to see the stocks they have in common."),
  );
}

function showMoreButton(label: string, key: string, onClick: () => void): HTMLElement {
  const button = el("button", { type: "button", class: "btn small more", "data-key": key }, label);
  button.addEventListener("click", onClick);
  return button;
}

function pairSection(s: Snapshot): HTMLElement {
  if (!s.pair) return el("div");
  const a = s.funds[s.pair[0]]!;
  const b = s.funds[s.pair[1]]!;
  const { overlap, common } = pairOverlap(a.holdings, b.holdings);
  const shown = s.showAllPair ? common : common.slice(0, PAIR_ROWS);

  const section = el(
    "section",
    {},
    el("h2", {}, `${a.scheme.name} × ${b.scheme.name}`),
    el(
      "p",
      { class: "note", style: "margin: 0 0 12px" },
      common.length === 0
        ? "These two funds have no stocks in common."
        : `${pct(overlap)} overlap across ${common.length.toLocaleString("en-IN")} common ${common.length === 1 ? "stock" : "stocks"}.`,
    ),
  );
  if (common.length === 0) return section;

  const body = el("tbody");
  for (const row of shown) {
    const security = s.securities[row.isin];
    body.append(
      el(
        "tr",
        {},
        el("td", { class: "wrap-ok" }, security?.name ?? row.isin),
        el("td", { class: "via sector" }, security?.sector ?? ""),
        el("td", {}, pct(row.a)),
        el("td", {}, pct(row.b)),
        el("td", {}, pct(row.shared)),
      ),
    );
  }
  section.append(
    el(
      "div",
      { class: "scroll" },
      el(
        "table",
        {},
        el(
          "thead",
          {},
          el(
            "tr",
            {},
            el("th", { scope: "col" }, "Stock"),
            el("th", { scope: "col", class: "via sector" }, "Sector"),
            el("th", { scope: "col", title: a.scheme.name }, `In ${a.tag}`),
            el("th", { scope: "col", title: b.scheme.name }, `In ${b.tag}`),
            el("th", { scope: "col" }, "Shared"),
          ),
        ),
        body,
      ),
    ),
  );
  if (shown.length < common.length) {
    section.append(
      showMoreButton(`Show all ${common.length.toLocaleString("en-IN")} common stocks`, "more-pair", () => {
        s.showAllPair = true;
        renderOutput();
      }),
    );
  }
  return section;
}

function exposureSection(s: Snapshot): HTMLElement {
  const { exposures, total } = s.analysis;
  const shown = s.showAllExposure ? exposures : exposures.slice(0, EXPOSURE_ROWS);

  const csvButton = el("button", { type: "button", class: "btn small" }, "Download CSV");
  csvButton.addEventListener("click", () => downloadExposureCsv(s));

  const body = el("tbody");
  for (const row of shown) {
    const security = s.securities[row.isin];
    body.append(
      el(
        "tr",
        {},
        el("td", { class: "wrap-ok" }, security?.name ?? row.isin),
        el("td", { class: "via sector" }, security?.sector ?? ""),
        el("td", { "data-label": "Share" }, pct(row.pct)),
        el("td", { "data-label": "Value" }, `₹${inr((row.pct / 100) * total)}`),
        el("td", { class: "via", "data-label": "Held via" }, row.via.map((v) => `${s.funds[v.fund]!.tag} ${pct(v.weight)}`).join(" · ")),
      ),
    );
  }

  const section = el(
    "section",
    {},
    el("div", { class: "sec-head" }, el("h2", {}, "Your stock exposure"), csvButton),
    el(
      "div",
      { class: "scroll" },
      el(
        "table",
        { class: "stack" },
        el(
          "thead",
          {},
          el(
            "tr",
            {},
            el("th", { scope: "col" }, "Stock"),
            el("th", { scope: "col", class: "via sector" }, "Sector"),
            el("th", { scope: "col" }, "% of portfolio"),
            el("th", { scope: "col" }, "Value"),
            el("th", { scope: "col", class: "via" }, "Held via (weight in that fund)"),
          ),
        ),
        body,
      ),
    ),
  );
  if (shown.length < exposures.length) {
    section.append(
      showMoreButton(`Show all ${exposures.length.toLocaleString("en-IN")} stocks`, "more-exp", () => {
        s.showAllExposure = true;
        renderOutput();
      }),
    );
  }
  return section;
}

// ---------- save, load, download ----------

function downloadExposureCsv(s: Snapshot): void {
  const header = [
    "ISIN",
    "Stock",
    "Sector",
    "% of portfolio",
    "Value (INR)",
    "Funds holding",
    ...s.funds.map((f) => `${f.tag}: ${f.scheme.name} (% of fund)`),
  ];
  const lines = s.analysis.exposures.map((row) => {
    const security = s.securities[row.isin];
    const weights = new Map(row.via.map((v) => [v.fund, v.weight]));
    return [
      row.isin,
      security?.name ?? "",
      security?.sector ?? "",
      row.pct.toFixed(4),
      ((row.pct / 100) * s.analysis.total).toFixed(2),
      row.via.length,
      ...s.funds.map((_, index) => weights.get(index) ?? ""),
    ];
  });
  const asOf = s.funds[0]?.scheme.as_of ?? "";
  downloadFile(`fund-overlap-exposure-${asOf}.csv`, "text/csv;charset=utf-8", toCsv([header, ...lines]));
}

saveBtn.addEventListener("click", () => {
  const file: PortfolioFile = {
    app: "fund-overlap",
    version: 1,
    funds: rows.map((row) => ({ id: row.id, name: schemes.get(row.id)!.name, amount: parseAmount(row.amount) ?? 0 })),
  };
  downloadFile("fund-overlap-portfolio.json", "application/json", JSON.stringify(file, null, 2) + "\n");
});

$("load").addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", async () => {
  const file = fileInput.files?.[0];
  fileInput.value = "";
  if (!file) return;
  try {
    const loaded = parsePortfolioFile(await file.text());
    const seen = new Set<string>();
    const known = loaded.filter((f) => schemes.has(f.id) && !seen.has(f.id) && seen.add(f.id));
    rows = known.map((f) => ({ id: f.id, amount: f.amount > 0 ? formatAmount(f.amount) : "" }));
    persist();
    renderFunds();
    updateControls();
    const skipped = loaded.length - known.length;
    setMsg(
      skipped > 0
        ? `Loaded ${known.length} ${known.length === 1 ? "fund" : "funds"}. ${skipped} in the file ${skipped === 1 ? "is" : "are"} not in the current data and ${skipped === 1 ? "was" : "were"} skipped.`
        : "",
    );
  } catch (error) {
    setMsg(error instanceof Error ? error.message : "Could not read that file.", true);
  }
});

analyseBtn.addEventListener("click", () => void runAnalysis());

// ---------- theme ----------

/**
 * Feature flag, set at build time: `VITE_ENABLE_THEMING=true npm run dev` (or build).
 * Off by default, and the app is then always light: the switcher is removed and
 * both ?theme= and a saved choice are ignored. index.html starts with data-theme="light".
 */
const THEMING = import.meta.env.VITE_ENABLE_THEMING === "true";

function applyTheme(choice: string): void {
  if (choice === "light" || choice === "dark") document.documentElement.dataset.theme = choice;
  else delete document.documentElement.dataset.theme;
  for (const button of $("themeSeg").querySelectorAll("button")) {
    button.setAttribute("aria-pressed", String(button.dataset.themeChoice === (choice === "light" || choice === "dark" ? choice : "system")));
  }
}

if (THEMING) {
  $("themeSeg").addEventListener("click", (event) => {
    const choice = (event.target as HTMLElement).closest("button")?.dataset.themeChoice;
    if (!choice) return;
    saveLocal("theme", choice);
    applyTheme(choice);
  });
} else {
  $("themebar").remove();
}

// ---------- start ----------

async function init(): Promise<void> {
  if (THEMING) {
    // ?theme=dark or ?theme=light in the address forces a theme for that visit (used for screenshots).
    applyTheme(new URLSearchParams(location.search).get("theme") ?? loadLocal<string>("theme") ?? "system");
  }

  let index: Scheme[];
  try {
    index = await loadIndex();
  } catch {
    $("asof").textContent = "Could not load fund data. Reload the page to try again.";
    return;
  }
  const eligible = index.filter((scheme) => scheme.equity_pct >= MIN_EQUITY_PCT);
  schemes = new Map(eligible.map((scheme) => [scheme.id, scheme]));
  search = createSearch(eligible.map((scheme) => ({ id: scheme.id, text: `${scheme.name} ${amcName(scheme.amc)}` })));

  const latest = eligible.map((scheme) => scheme.as_of).sort().at(-1);
  const houses = new Set(eligible.map((scheme) => scheme.amc)).size;
  const date = latest
    ? new Date(`${latest}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })
    : "";
  $("asof").textContent = `Holdings as of ${date} · ${eligible.length} funds from ${houses} fund houses`;

  renderHouses(eligible);

  const saved = loadLocal<unknown>("portfolio");
  if (Array.isArray(saved)) {
    const seen = new Set<string>();
    const valid = saved.filter(
      (row): row is Row =>
        typeof row?.id === "string" && typeof row?.amount === "string" && schemes.has(row.id) && !seen.has(row.id) && !!seen.add(row.id),
    );
    rows = valid.map((row) => ({ id: row.id, amount: row.amount }));
    if (valid.length < saved.length) {
      setMsg(`${saved.length - valid.length} of your saved funds are not in the current data and were removed.`);
      persist();
    }
  }

  searchInput.disabled = false;
  renderFunds();
  updateControls();
}

const formatDate = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });

/** Lists each fund house with its fund count and data date; houses behind the newest date are flagged. */
function renderHouses(list: Scheme[]) {
  const houses = summariseHouses(list);
  if (!houses.length) return;
  const newest = houses.reduce((max, h) => (h.asOf > max ? h.asOf : max), "");
  $("houses").replaceChildren(
    ...houses.map((h) =>
      el(
        "tr",
        {},
        el("td", {}, amcName(h.amc)),
        el("td", { class: "num" }, String(h.funds)),
        el("td", {}, formatDate(h.asOf), h.asOf < newest ? el("span", { class: "stale" }, "older") : null),
      ),
    ),
  );
  $("housesSection").hidden = false;
}

void init();
