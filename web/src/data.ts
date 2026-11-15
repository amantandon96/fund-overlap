import type { Holding, Scheme, Security } from "./types";

const base = `${import.meta.env.BASE_URL}data/`;

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(base + path);
  if (!response.ok) throw new Error(`Could not load ${path} (${response.status})`);
  return (await response.json()) as T;
}

export const loadIndex = () => getJson<Scheme[]>("index.json");

let securities: Promise<Record<string, Security>> | undefined;
/** ISIN to name and sector; fetched once, on the first analysis. */
export function loadSecurities(): Promise<Record<string, Security>> {
  securities ??= getJson<Record<string, Security>>("securities.json").catch((error) => {
    securities = undefined;
    throw error;
  });
  return securities;
}

const holdings = new Map<string, Promise<Holding[]>>();
/** A scheme's equity holdings; each scheme's file is fetched once. */
export function loadHoldings(scheme: Scheme): Promise<Holding[]> {
  let pending = holdings.get(scheme.id);
  if (!pending) {
    pending = getJson<Holding[]>(`holdings/${scheme.amc}/${scheme.id}.json`).catch((error) => {
      holdings.delete(scheme.id);
      throw error;
    });
    holdings.set(scheme.id, pending);
  }
  return pending;
}

const AMC_NAMES: Record<string, string> = {
  axis: "Axis",
  hdfc: "HDFC",
  motilal: "Motilal Oswal",
  navi: "Navi",
  nippon: "Nippon India",
  ppfas: "Parag Parikh",
};
export const amcName = (slug: string) => AMC_NAMES[slug] ?? slug;
