// What the dashboard copies from core/kinds/country_risk.py: the heats, the
// lenses and the trend step, in the words the agent was given. Change them
// together with the kind.
import type { Tracker } from "../api";

export type Lens = { heat: string; summary: string; detail: string; latest_event?: string | null; source_urls: string[]; held_until?: string };
export type CountryState = {
  level: string; peace_score: number; peace_score_reason: string; overview: string; outlook: string;
  // Absent on records judged before 2026-10-28, which filed a conflict list instead; they stand until the next run.
  lenses?: Record<string, Lens>; trend?: string; peace_score_change?: number;
};

export const HEAT_RANK: Record<string, number> = { calm: 0, dormant: 1, cold: 2, warm: 3, hot: 4 };

export const LEGEND: [rank: number, word: string, meaning: string][] = [
  [4, "hot", "organized violence in the last 30 days, or imminent"],
  [3, "warm", "violence with casualties in the last 12 months, or active mobilization"],
  [2, "cold", "tension without violence in the last 12 months"],
  [1, "dormant", "frozen or historic, no activity in over a year, could reignite"],
  [0, "calm", "nothing of the kind in the last 12 months"],
  [-1, "no data", "no tracker, or not judged on this lens yet"],
];

/** The six things judged for every country, in the record's order. */
export const LENSES: [key: string, word: string][] = [
  ["security", "security"],
  ["internal_stability", "internal stability"],
  ["political_stability", "political stability"],
  ["antisemitism", "antisemitism"],
  ["islam", "Islam"],
  ["migration", "migration"],
];

export const TREND_LEGEND: [word: string, meaning: string][] = [
  ["improving", "peace score up 5 or more since the previous judgment"],
  ["stable", "within 5 points"],
  ["worsening", "down 5 or more"],
  ["none", "one judgment so far, or no tracker"],
];

export function countryState(tracker: Tracker): CountryState | undefined {
  return tracker.kind === "country_risk" ? (tracker.latest_assessment?.state as CountryState | undefined) : undefined;
}

/** One lens's heat on a tracker's latest judgment; null when the tracker has no such lens. */
export function lensHeat(tracker: Tracker, lens: string): { heat: string; rank: number } | null {
  const heat = countryState(tracker)?.lenses?.[lens]?.heat;
  return heat === undefined ? null : { heat, rank: HEAT_RANK[heat] ?? -1 };
}

/** Every lens's heat rank on a tracker, for the globe's paint. */
export function lensRanks(tracker: Tracker): Record<string, number> {
  return Object.fromEntries(LENSES.map(([key]) => [key, lensHeat(tracker, key)?.rank ?? -1]));
}
