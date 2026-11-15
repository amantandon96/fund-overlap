/** Everything here stays on the user's device: browser storage and local files only. */

const PREFIX = "fund-overlap:";

export function loadLocal<T>(key: string): T | null {
  try {
    const raw = localStorage.getItem(PREFIX + key);
    return raw === null ? null : (JSON.parse(raw) as T);
  } catch {
    return null; // storage blocked, or the value is corrupt
  }
}

export function saveLocal(key: string, value: unknown): void {
  try {
    localStorage.setItem(PREFIX + key, JSON.stringify(value));
  } catch {
    // Private windows and blocked storage: the app still works, it just won't remember.
  }
}

/** Hands the user a file to save. */
export function downloadFile(filename: string, mime: string, content: string): void {
  const url = URL.createObjectURL(new Blob([content], { type: mime }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function toCsv(rows: (string | number)[][]): string {
  const cell = (value: string | number) => {
    const text = String(value);
    return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
  };
  // The leading BOM makes Excel read the file as UTF-8.
  return "﻿" + rows.map((row) => row.map(cell).join(",")).join("\r\n") + "\r\n";
}

export interface PortfolioFile {
  app: "fund-overlap";
  version: 1;
  funds: { id: string; name: string; amount: number }[];
}

/** Reads a saved portfolio file, returning its fund rows or throwing a readable error. */
export function parsePortfolioFile(text: string): { id: string; amount: number }[] {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new Error("That file is not a saved portfolio.");
  }
  const funds = (parsed as Partial<PortfolioFile> | null)?.funds;
  if (!Array.isArray(funds)) throw new Error("That file is not a saved portfolio.");
  return funds
    .filter((f) => f && typeof f.id === "string")
    .map((f) => ({ id: f.id, amount: Number(f.amount) }));
}
