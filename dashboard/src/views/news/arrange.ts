import type { Observation, Tracker } from "../../api";

/** The News screen, in Hebrew: a country's desk, split into the two columns Guy
 *  reads, war (the security lens) and politics (the political and internal
 *  stability lenses). Each lens shows the desk's latest digest, the state of
 *  play with its figure, and under it the items the desk filed, by day, newest
 *  first. Only desk rows carry a lens; the weekly brief's pages stay out. */
export type Column = "war" | "politics";
export const COLUMNS: { key: Column; title: string; lenses: string[] }[] = [
  { key: "war", title: "מלחמה", lenses: ["security"] },
  { key: "politics", title: "פוליטיקה", lenses: ["political_stability", "internal_stability"] },
];
export const LENS_HE: Record<string, string> = {
  security: "ביטחון", political_stability: "יציבות פוליטית", internal_stability: "יציבות פנימית",
};

export type Bar = { label: string; value: number; note?: string };
export type Figure = { title: string; unit?: string; bars: Bar[] };
export type Day = { day: string; items: Observation[] };
export type LensNews = { lens: string; digest: Observation | null; days: Day[] };
export const DAYS_SHOWN = 7;

export function deskTrackers(trackers: Tracker[]): Tracker[] {
  return trackers.filter((tracker) => tracker.kind === "country_risk" && tracker.status === "active" && Array.isArray(tracker.subject.desk) && tracker.subject.desk.length > 0);
}

export function arrangeNews(observations: Observation[], now = new Date()): Record<Column, LensNews[]> {
  const since = new Date(now.getTime() - DAYS_SHOWN * 86_400_000);
  const sorted = [...observations]
    .filter((observation) => typeof observation.payload.lens === "string")
    .sort((a, b) => b.observed_at.localeCompare(a.observed_at));
  const forLens = (lens: string): LensNews => {
    const rows = sorted.filter((observation) => observation.payload.lens === lens);
    const days: Day[] = [];
    for (const item of rows.filter((row) => !row.payload.digest && new Date(row.observed_at) >= since)) {
      const day = dayOf(item.observed_at);
      const last = days[days.length - 1];
      if (last && last.day === day) last.items.push(item);
      else days.push({ day, items: [item] });
    }
    return { lens, digest: rows.find((row) => row.payload.digest === true) ?? null, days };
  };
  return { war: COLUMNS[0].lenses.map(forLens), politics: COLUMNS[1].lenses.map(forLens) };
}

/** The local calendar day, as the reader sees it: a row dated by day only is filed at midnight Jerusalem,
 *  which is the evening before in UTC. */
export function dayOf(iso: string): string {
  const date = new Date(iso);
  const two = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${two(date.getMonth() + 1)}-${two(date.getDate())}`;
}

export function figureOf(digest: Observation | null): Figure | null {
  const figure = digest?.payload.figure as Figure | undefined;
  return figure && Array.isArray(figure.bars) && figure.bars.length ? figure : null;
}

export function domainOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}
