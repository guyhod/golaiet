// Finding things on the board and in a tracker's rows: pure, so Vitest covers it.
import type { Assessment, Observation } from "../../api";
import type { Board, Campaign, Selection, Station, Track } from "./types";

/** A lane by its id, or by the name a panel shows for it (its short name or title). */
export function findLane(board: Board, key: string): Campaign | undefined {
  const wanted = key.trim().toLowerCase();
  return (
    board.lanes.find((lane) => lane.id.toLowerCase() === wanted) ??
    board.lanes.find((lane) => lane.short.toLowerCase() === wanted) ??
    board.lanes.find((lane) => lane.title.toLowerCase() === wanted)
  );
}

export function findStation(lane: Campaign, id: string): { track: Track; station: Station } | undefined {
  for (const track of lane.tracks) {
    for (const station of track.stations ?? []) if (station.id === id) return { track, station };
  }
  return undefined;
}

/** The lanes that have something due on a day of the horizon. */
export function campaignsOn(board: Board, date: string): Set<string> {
  const day = board.horizon.find((candidate) => candidate.date === date);
  return new Set((day?.items ?? []).map((item) => item.campaign));
}

/** What a focus pushed from a conversation opens: a practice's tile, a lane, or one station of it. */
export function selectionFor(board: Board, slug: string, params: Record<string, unknown>): Selection {
  if (board.pulse.some((tile) => tile.id === slug)) return { kind: "practice", id: slug };
  return typeof params.station === "string"
    ? { kind: "station", campaign: slug, station: params.station }
    : { kind: "lane", campaign: slug };
}

/** The day a fact counts for, as the board writes days. A fact dated to a bare day is stored as that
 *  day's midnight in Jerusalem, which is still the evening before in UTC, so the day is read in Jerusalem. */
export function dayOf(observedAt: string): string {
  return new Date(observedAt).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "Asia/Jerusalem" });
}

export type Fact = Observation & { retracted: boolean };

/** A tracker's facts, newest first, for the drawer's History. For one station: the facts that name it,
 *  and the facts that were the evidence of a change that touched it. A fact that was taken back, and the
 *  one that took it back, are kept and marked. */
export function historyOf(observations: Observation[], assessments: Assessment[], station?: string): Fact[] {
  const retracted = new Set(observations.map((fact) => fact.payload.retracts).filter((id) => typeof id === "number"));
  let kept = observations;
  if (station) {
    const cited = new Set<number>();
    for (const assessment of assessments) {
      const changed = assessment.state.changed;
      if (Array.isArray(changed) && changed.includes(station)) assessment.evidence_ids.forEach((id) => cited.add(id));
    }
    kept = observations.filter((fact) => fact.payload.station === station || cited.has(fact.id));
  }
  return [...kept]
    .sort((a, b) => b.observed_at.localeCompare(a.observed_at) || b.id - a.id)
    .map((fact) => ({ ...fact, retracted: retracted.has(fact.id) || "retracts" in fact.payload }));
}
