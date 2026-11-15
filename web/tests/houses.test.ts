import { describe, expect, it } from "vitest";
import { summariseHouses } from "../src/houses";
import type { Scheme } from "../src/types";

const scheme = (id: string, amc: string, as_of: string): Scheme => ({ id, name: id, amc, as_of, equity_pct: 90, holdings: 10 });

describe("summariseHouses", () => {
  it("counts funds and keeps the newest as_of per house", () => {
    const rows = summariseHouses([
      scheme("a1", "axis", "2026-09-30"),
      scheme("a2", "axis", "2026-10-31"),
      scheme("n1", "navi", "2026-09-30"),
    ]);
    expect(rows).toEqual([
      { amc: "axis", funds: 2, asOf: "2026-10-31" },
      { amc: "navi", funds: 1, asOf: "2026-09-30" },
    ]);
  });

  it("returns nothing for no schemes", () => {
    expect(summariseHouses([])).toEqual([]);
  });
});
