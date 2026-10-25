// The overview's order and filter: pure, so Vitest covers it.
import type { Tracker } from "../../api";

export type SortBy = "level" | "score" | "trend" | "recent";
/** The orders offered, with the words on the control. Each puts what needs attention first. */
export const SORTS: [SortBy, string][] = [
  ["level", "hottest"],
  ["score", "lowest score"],
  ["trend", "worsening"],
  ["recent", "latest observed"],
];

/** The score a judgment carries: a country's peace score, a topic's optional score; null when the kind has none. */
export function scoreOf(tracker: Tracker): number | null {
  const state = tracker.latest_assessment?.state ?? {};
  const score = state.peace_score ?? state.score;
  return typeof score === "number" ? score : null;
}

/** How the score moved since the previous judgment, as the country kind derives it; null before a second judgment. */
export function trendOf(tracker: Tracker): { word: string; change: number } | null {
  const state = tracker.latest_assessment?.state ?? {};
  return typeof state.trend === "string" && typeof state.peace_score_change === "number"
    ? { word: state.trend, change: state.peace_score_change }
    : null;
}

/** The levels judged among these trackers, hottest first, for the filter chips. */
export function levelsOf(trackers: Tracker[]): { level: string; rank: number }[] {
  const seen = new Map<string, number>();
  for (const tracker of trackers) if (tracker.level) seen.set(tracker.level, tracker.level_rank);
  return [...seen].map(([level, rank]) => ({ level, rank })).sort((a, b) => b.rank - a.rank || a.level.localeCompare(b.level));
}

// Trackers without the sorted value go last; ties fall back to the level order.
function compareNullable(a: number | null, b: number | null): number {
  if (a === null || b === null) return a === b ? 0 : a === null ? 1 : -1;
  return a - b;
}

function byLevel(a: Tracker, b: Tracker): number {
  return b.level_rank - a.level_rank || (b.latest_observation_at ?? "").localeCompare(a.latest_observation_at ?? "");
}

/** The active trackers at the chosen level (null for all), in the chosen order. */
export function arrange(trackers: Tracker[], sort: SortBy, level: string | null): Tracker[] {
  const shown = trackers.filter((tracker) => tracker.status === "active" && (level === null || tracker.level === level));
  const compare: Record<SortBy, (a: Tracker, b: Tracker) => number> = {
    level: byLevel,
    score: (a, b) => compareNullable(scoreOf(a), scoreOf(b)) || byLevel(a, b),
    trend: (a, b) => compareNullable(trendOf(a)?.change ?? null, trendOf(b)?.change ?? null) || byLevel(a, b),
    recent: (a, b) => (b.latest_observation_at ?? "").localeCompare(a.latest_observation_at ?? "") || byLevel(a, b),
  };
  return shown.sort(compare[sort]);
}
