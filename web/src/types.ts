/** One entry of data/index.json. */
export interface Scheme {
  id: string;
  name: string;
  amc: string;
  as_of: string;
  /** Sum of the scheme's equity weights, in percent of its net assets. */
  equity_pct: number;
  holdings: number;
  descriptor?: string;
}

/** One row of data/holdings/<amc>/<id>.json: ISIN and weight in percent of net assets. */
export type Holding = [isin: string, weight: number];

/** One value of data/securities.json. */
export interface Security {
  name: string;
  sector: string;
}
