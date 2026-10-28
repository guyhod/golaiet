import { describe, expect, it } from "vitest";
import type { Tracker } from "../../api";
import { arrange, levelOf, levelsOf, scoreOf, trendOf } from "./arrange";

function tracker(slug: string, level: string | null, rank: number, state: Record<string, unknown> | null, observed = "2026-10-20"): Tracker {
  return {
    slug, title: slug, kind: "country_risk", status: "active", view: "globe", subject: {}, observations: 1,
    latest_observation_at: observed, level, level_rank: rank,
    latest_assessment: state && { id: 1, at: observed, state, reason: "", evidence_ids: [] },
  };
}

const egypt = tracker("egy", "warm", 3, { peace_score: 66, trend: "stable", peace_score_change: 1 });
const syria = tracker("syr", "hot", 4, { peace_score: 34, trend: "improving", peace_score_change: 4 }, "2026-10-19");
const gaza = tracker("pse", "hot", 4, { peace_score: 16, trend: "worsening", peace_score_change: -5 }, "2026-10-21");
const portugal = tracker("prt", "warm", 3, { peace_score: 90, lenses: { antisemitism: { heat: "cold" }, islam: { heat: "warm" } } });
const belgium = tracker("bel", "hot", 4, { peace_score: 80, lenses: { antisemitism: { heat: "hot" }, islam: { heat: "calm" } } });
const unjudged = tracker("new", null, -1, null, "2026-10-22");
const paused = { ...tracker("old", "hot", 4, { peace_score: 1 }), status: "paused" as const };
const all = [egypt, syria, gaza, portugal, belgium, unjudged, paused];

describe("arrange", () => {
  it("defaults to hottest first, latest observed within a level, and drops paused trackers", () => {
    expect(arrange([...all], "level", null).map((t) => t.slug)).toEqual(["pse", "bel", "syr", "egy", "prt", "new"]);
  });
  it("orders by lowest score with unscored trackers last", () => {
    expect(arrange([...all], "score", null).map((t) => t.slug)).toEqual(["pse", "syr", "egy", "bel", "prt", "new"]);
  });
  it("orders by worsening first, then trackers without a trend", () => {
    expect(arrange([...all], "trend", null).map((t) => t.slug)).toEqual(["pse", "egy", "syr", "bel", "prt", "new"]);
  });
  it("orders by latest observation", () => {
    expect(arrange([...all], "recent", null).map((t) => t.slug)).toEqual(["new", "pse", "bel", "egy", "prt", "syr"]);
  });
  it("filters to one level", () => {
    expect(arrange([...all], "level", "warm").map((t) => t.slug)).toEqual(["egy", "prt"]);
  });
  it("filters to one trend", () => {
    expect(arrange([...all], "level", null, null, "worsening").map((t) => t.slug)).toEqual(["pse"]);
    expect(arrange([...all], "level", null, null, "stable").map((t) => t.slug)).toEqual(["egy"]);
    expect(arrange([...all], "level", "hot", null, "improving").map((t) => t.slug)).toEqual(["syr"]);
  });
  it("reads countries through a lens and leaves out trackers not judged on it", () => {
    expect(arrange([...all], "level", null, "antisemitism").map((t) => t.slug)).toEqual(["bel", "prt"]);
    expect(arrange([...all], "level", "warm", "islam").map((t) => t.slug)).toEqual(["prt"]);
    expect(levelOf(portugal, "islam")).toEqual({ level: "warm", rank: 3 });
    expect(levelOf(egypt, "islam")).toEqual({ level: null, rank: -1 });
    expect(levelsOf(all, "antisemitism")).toEqual([{ level: "hot", rank: 4 }, { level: "cold", rank: 2 }]);
  });
});

describe("the judgment's score and trend", () => {
  it("reads a country's peace score or a topic's score, and nothing otherwise", () => {
    expect(scoreOf(portugal)).toBe(90);
    expect(scoreOf(tracker("t", "watch", 1, { level: "watch", score: 40 }))).toBe(40);
    expect(scoreOf(tracker("t", "watch", 1, { level: "watch" }))).toBeNull();
    expect(scoreOf(unjudged)).toBeNull();
  });
  it("needs both the word and the change for a trend", () => {
    expect(trendOf(gaza)).toEqual({ word: "worsening", change: -5 });
    expect(trendOf(portugal)).toBeNull();
  });
  it("lists the judged levels hottest first", () => {
    expect(levelsOf(all, null)).toEqual([{ level: "hot", rank: 4 }, { level: "warm", rank: 3 }]);
  });
});
