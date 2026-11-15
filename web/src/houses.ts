import type { Scheme } from "./types";

export interface HouseSummary {
  amc: string;
  funds: number;
  /** Latest portfolio date (YYYY-MM-DD) among this house's funds. */
  asOf: string;
}

/** One row per fund house: how many funds it contributes and how fresh its newest data is. Sorted by house slug. */
export function summariseHouses(schemes: Scheme[]): HouseSummary[] {
  const byHouse = new Map<string, HouseSummary>();
  for (const scheme of schemes) {
    const house = byHouse.get(scheme.amc) ?? { amc: scheme.amc, funds: 0, asOf: "" };
    house.funds += 1;
    if (scheme.as_of > house.asOf) house.asOf = scheme.as_of;
    byHouse.set(scheme.amc, house);
  }
  return [...byHouse.values()].sort((a, b) => a.amc.localeCompare(b.amc));
}
