import type { Holding } from "./types";

export interface CommonHolding {
  isin: string;
  /** Weight in the first fund, percent of its net assets. */
  a: number;
  /** Weight in the second fund. */
  b: number;
  /** The smaller of the two: this stock's contribution to the overlap. */
  shared: number;
}

export interface PairOverlap {
  /** Sum of shared weights, in percent (0 to 100). */
  overlap: number;
  /** Stocks held by both funds, largest shared weight first. */
  common: CommonHolding[];
}

/**
 * Overlap between two funds: for every stock both hold, take the smaller of
 * the two weights, and add those up. Symmetric, and bounded by each fund's
 * equity share.
 */
export function pairOverlap(a: Holding[], b: Holding[]): PairOverlap {
  const weightsA = new Map(a);
  const common: CommonHolding[] = [];
  let overlap = 0;
  for (const [isin, wb] of b) {
    const wa = weightsA.get(isin);
    if (wa === undefined) continue;
    const shared = Math.min(wa, wb);
    overlap += shared;
    common.push({ isin, a: wa, b: wb, shared });
  }
  common.sort((x, y) => y.shared - x.shared);
  return { overlap, common };
}

export interface FundInput {
  amount: number;
  holdings: Holding[];
}

export interface Exposure {
  isin: string;
  /** Share of the whole portfolio (all amounts entered) in this stock, in percent. */
  pct: number;
  /** Which funds hold it: index into the input array, and the weight inside that fund. */
  via: { fund: number; weight: number }[];
}

export interface Analysis {
  /** Sum of all amounts entered. */
  total: number;
  /** matrix[i][j] is the overlap between fund i and fund j in percent; the diagonal is null. */
  matrix: (number | null)[][];
  /** Every stock held by any fund, largest portfolio share first. */
  exposures: Exposure[];
  uniqueStocks: number;
  /** Percent of the portfolio in stocks that two or more of the funds hold. */
  duplicatedPct: number;
  /** Percent of the portfolio in its ten largest stocks. */
  top10Pct: number;
  /** Percent of the portfolio in equity holdings at all (the rest is debt, cash and so on). */
  equityPct: number;
}

/** Portfolio-level analysis of a set of funds, weighted by the amount in each. */
export function analyse(funds: FundInput[]): Analysis {
  const total = funds.reduce((sum, f) => sum + f.amount, 0);

  const matrix: (number | null)[][] = funds.map(() => funds.map(() => null));
  for (let i = 0; i < funds.length; i++) {
    for (let j = i + 1; j < funds.length; j++) {
      const { overlap } = pairOverlap(funds[i]!.holdings, funds[j]!.holdings);
      matrix[i]![j] = overlap;
      matrix[j]![i] = overlap;
    }
  }

  const byIsin = new Map<string, Exposure>();
  funds.forEach((fund, index) => {
    const share = total > 0 ? fund.amount / total : 0;
    for (const [isin, weight] of fund.holdings) {
      let exposure = byIsin.get(isin);
      if (!exposure) {
        exposure = { isin, pct: 0, via: [] };
        byIsin.set(isin, exposure);
      }
      exposure.pct += share * weight;
      exposure.via.push({ fund: index, weight });
    }
  });
  const exposures = [...byIsin.values()].sort((x, y) => y.pct - x.pct);

  const sum = (items: Exposure[]) => items.reduce((s, e) => s + e.pct, 0);
  return {
    total,
    matrix,
    exposures,
    uniqueStocks: exposures.length,
    duplicatedPct: sum(exposures.filter((e) => e.via.length >= 2)),
    top10Pct: sum(exposures.slice(0, 10)),
    equityPct: sum(exposures),
  };
}
