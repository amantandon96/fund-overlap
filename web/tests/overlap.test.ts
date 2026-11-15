import { describe, expect, it } from "vitest";
import { analyse, pairOverlap } from "../src/overlap";
import { createSearch } from "../src/search";
import { parsePortfolioFile, toCsv } from "../src/storage";
import type { Holding } from "../src/types";

const A: Holding[] = [["X", 8], ["Y", 5], ["Z", 2]];
const B: Holding[] = [["X", 5], ["Y", 7], ["W", 10]];

describe("pairOverlap", () => {
  it("sums the smaller weight of each common stock", () => {
    const result = pairOverlap(A, B);
    expect(result.overlap).toBe(10); // min(8,5) + min(5,7)
    expect(result.common.map((c) => c.isin)).toEqual(["X", "Y"]);
    expect(result.common[0]).toEqual({ isin: "X", a: 8, b: 5, shared: 5 });
  });

  it("is symmetric", () => {
    expect(pairOverlap(A, B).overlap).toBe(pairOverlap(B, A).overlap);
  });

  it("is zero for funds with nothing in common", () => {
    expect(pairOverlap(A, [["Q", 50]])).toEqual({ overlap: 0, common: [] });
  });

  it("equals the equity total for a fund compared with itself", () => {
    expect(pairOverlap(A, A).overlap).toBe(15);
  });
});

describe("analyse", () => {
  const result = analyse([
    { amount: 300, holdings: A },
    { amount: 100, holdings: B },
  ]);

  it("leaves the diagonal empty and mirrors the matrix", () => {
    expect(result.matrix).toEqual([[null, 10], [10, null]]);
  });

  it("weights exposure by the amount in each fund", () => {
    const x = result.exposures.find((e) => e.isin === "X")!;
    expect(x.pct).toBeCloseTo(0.75 * 8 + 0.25 * 5); // 7.25
    expect(x.via).toEqual([{ fund: 0, weight: 8 }, { fund: 1, weight: 5 }]);
  });

  it("sorts exposures largest first", () => {
    expect(result.exposures.map((e) => e.isin)).toEqual(["X", "Y", "W", "Z"]);
  });

  it("reports the summary figures", () => {
    expect(result.total).toBe(400);
    expect(result.uniqueStocks).toBe(4);
    expect(result.duplicatedPct).toBeCloseTo(7.25 + 5.5); // X and Y
    expect(result.equityPct).toBeCloseTo(0.75 * 15 + 0.25 * 22);
    expect(result.top10Pct).toBeCloseTo(result.equityPct);
  });

  it("depends only on the proportions between amounts", () => {
    const scaled = analyse([
      { amount: 3, holdings: A },
      { amount: 1, holdings: B },
    ]);
    expect(scaled.duplicatedPct).toBeCloseTo(result.duplicatedPct);
  });
});

describe("search", () => {
  const search = createSearch([
    { id: "hdfc-mid", text: "HDFC Mid Cap Fund HDFC" },
    { id: "hdfc-flexi", text: "HDFC Flexi Cap Fund HDFC" },
    { id: "nippon-mid", text: "Nippon India Growth Mid Cap Fund Nippon India" },
    { id: "navi-next", text: "Navi Nifty Next 50 Index Fund Navi" },
  ]);

  it("matches word prefixes in any order", () => {
    expect(search("hdfc mid")).toEqual(["hdfc-mid"]);
    expect(search("mid hd")).toEqual(["hdfc-mid"]);
  });

  it("matches joined words such as midcap", () => {
    expect(search("midcap").sort()).toEqual(["hdfc-mid", "nippon-mid"]);
  });

  it("ranks a joined-word match by where it sits in the name", () => {
    const funds = createSearch([
      { id: "etf", text: "HDFC Nifty Midcap 150 ETF HDFC" },
      { id: "fund", text: "HDFC Mid Cap Fund HDFC" },
    ]);
    expect(funds("hdfc midcap")).toEqual(["fund", "etf"]);
  });

  it("ranks earlier matches first", () => {
    expect(search("mid")).toEqual(["hdfc-mid", "nippon-mid"]);
  });

  it("returns nothing for an empty query or no match", () => {
    expect(search("  ")).toEqual([]);
    expect(search("gold")).toEqual([]);
  });

  it("skips excluded ids and respects the limit", () => {
    expect(search("hdfc", 12, new Set(["hdfc-mid"]))).toEqual(["hdfc-flexi"]);
    expect(search("fund", 2)).toHaveLength(2);
  });
});

describe("storage helpers", () => {
  it("quotes CSV cells that need it", () => {
    expect(toCsv([["a", 'say "hi"', "x,y", 3]])).toBe('﻿a,"say ""hi""","x,y",3\r\n');
  });

  it("reads a saved portfolio and rejects other files", () => {
    const text = JSON.stringify({ app: "fund-overlap", version: 1, funds: [{ id: "a", name: "A", amount: 5 }] });
    expect(parsePortfolioFile(text)).toEqual([{ id: "a", amount: 5 }]);
    expect(() => parsePortfolioFile("not json")).toThrow();
    expect(() => parsePortfolioFile("{}")).toThrow();
  });
});
