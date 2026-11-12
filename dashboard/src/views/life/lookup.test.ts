import { expect, it } from "vitest";
import type { Assessment, Observation } from "../../api";
import { campaignsOn, dayOf, findStation, historyOf, laneOf, selectionFor } from "./lookup";
import type { Board, Campaign } from "./types";

const garden: Campaign = {
  id: "garden", title: "Garden and orchard", short: "Garden", _wide: false, _meta: "1 / 3",
  tracks: [{ caption: "Beds", stations: [{ id: "dig", label: "Dig the beds", state: "passed", date: "2031-03-06" }, { id: "fence", label: "Mend the fence", state: "current" }] }],
};
const board: Board = {
  today: "2031-03-10", burning: [], burning_more: 0, focus: [], focus_more: 0, trail: [], next: [], quiet: ["Boat"], lanes: [garden],
  pulse: [{ id: "stretch", label: "Stretching", color: "red", n: 2, since: "2031-03-08", note: "", events: [], unit: "days since", sub: "", dots: [], state: "warn" }],
  horizon: [{ date: "2031-03-12", label: "Mar 12", today: false, items: [{ label: "Garden", kind: "check", campaign: "garden" }] }],
};

function fact(id: number, day: string, payload: Record<string, unknown> = {}): Observation {
  return { id, observed_at: `${day}T00:00:00+02:00`, source_url: "", summary: `fact ${id}`, payload };
}
function change(id: number, changed: string[], evidence: number[]): Assessment {
  return { id, at: "2031-03-09T10:00:00Z", state: { changed }, reason: "He said so.", evidence_ids: evidence };
}

it("a station is found inside its lane", () => {
  expect(findStation(garden, "fence")?.track.caption).toBe("Beds");
  expect(findStation(garden, "pond")).toBeUndefined();
});

it("a lane the map does not draw is read from its tracker", () => {
  const tracker = {
    slug: "boat", title: "Boat repair", kind: "campaign", status: "paused" as const, view: "campaign_map", subject: { short: "Boat" },
    observations: 0, latest_observation_at: null, level: "steady", level_rank: 0, brief: "", recent_assessments: [], recent_observations: [],
    latest_assessment: change(1, [], []),
  };
  expect(laneOf(tracker)).toBeUndefined();
  const state = { level: "steady", changed: [], check: "2031-03-15", tracks: [{ stations: [{ id: "hull", label: "Sand the hull", state: "ahead" }] }] };
  const lane = laneOf({ ...tracker, latest_assessment: { ...change(1, [], []), state } });
  expect(lane && [lane.id, lane.title, lane.short, lane.check]).toEqual(["boat", "Boat repair", "Boat", "2031-03-15"]);
  expect(lane && findStation(lane, "hull")?.station.label).toBe("Sand the hull");
});

it("a day of the horizon names the lanes due on it", () => {
  expect([...campaignsOn(board, "2031-03-12")]).toEqual(["garden"]);
  expect(campaignsOn(board, "2031-03-13").size).toBe(0);
});

it("a pushed focus opens a practice, a lane, or one station", () => {
  expect(selectionFor(board, "stretch", {})).toEqual({ kind: "practice", id: "stretch" });
  expect(selectionFor(board, "garden", {})).toEqual({ kind: "lane", campaign: "garden" });
  expect(selectionFor(board, "garden", { station: "fence" })).toEqual({ kind: "station", campaign: "garden", station: "fence" });
});

it("a station's history is what names it and what was cited when it changed", () => {
  const facts = [fact(1, "2031-03-01"), fact(2, "2031-03-06", { station: "dig" }), fact(3, "2031-03-09"), fact(4, "2031-03-09", { station: "fence" })];
  const changes = [change(1, [], [1, 2]), change(2, ["fence"], [3])];
  expect(historyOf(facts, changes, "fence").map((item) => item.id)).toEqual([4, 3]);
  expect(historyOf(facts, changes, "dig").map((item) => item.id)).toEqual([2]);
  expect(historyOf(facts, changes).map((item) => item.id)).toEqual([4, 3, 2, 1]);
});

it("a fact's day is its Jerusalem day, not the UTC one", () => {
  expect(dayOf("2031-03-07T22:00:00Z")).toBe("Mar 8");
  expect(dayOf("2031-03-08T12:00:00+02:00")).toBe("Mar 8");
});

it("a fact that was taken back is kept and marked, with the one that took it back", () => {
  const facts = [fact(1, "2031-03-05"), fact(2, "2031-03-09"), fact(3, "2031-03-10", { retracts: 2 })];
  expect(historyOf(facts, []).map((item) => [item.id, item.retracted])).toEqual([[3, true], [2, true], [1, false]]);
});
