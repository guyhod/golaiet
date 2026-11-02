import type { Observation, Tracker } from "../../api";

/** The News screen: a country's desk items, split into the two columns Guy
 *  reads, War (the security lens) and Politics (the political and internal
 *  stability lenses), each grouped by day, newest first. Only items the desk
 *  filed carry a lens; the weekly brief's background pages stay out. */
export type Column = "war" | "politics";
export const COLUMNS: { key: Column; title: string; lenses: string[] }[] = [
  { key: "war", title: "War", lenses: ["security"] },
  { key: "politics", title: "Politics", lenses: ["political_stability", "internal_stability"] },
];

export type Day = { day: string; items: Observation[] };

export function deskTrackers(trackers: Tracker[]): Tracker[] {
  return trackers.filter((tracker) => tracker.kind === "country_risk" && tracker.status === "active" && Array.isArray(tracker.subject.desk) && tracker.subject.desk.length > 0);
}

export function arrangeNews(observations: Observation[]): Record<Column, Day[]> {
  const sorted = [...observations]
    .filter((observation) => typeof observation.payload.lens === "string")
    .sort((a, b) => b.observed_at.localeCompare(a.observed_at));
  const arranged = { war: [] as Day[], politics: [] as Day[] };
  for (const column of COLUMNS) {
    for (const observation of sorted) {
      if (!column.lenses.includes(observation.payload.lens as string)) continue;
      const day = observation.observed_at.slice(0, 10);
      const days = arranged[column.key];
      const last = days[days.length - 1];
      if (last && last.day === day) last.items.push(observation);
      else days.push({ day, items: [observation] });
    }
  }
  return arranged;
}

export function domainOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}
