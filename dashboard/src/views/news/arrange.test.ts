import { expect, it } from "vitest";
import type { Observation, Tracker } from "../../api";
import { arrangeNews, deskTrackers, domainOf } from "./arrange";

function item(id: number, at: string, lens: string | null, url = `https://www.reuters.com/${id}`): Observation {
  return { id, observed_at: at, source_url: url, summary: `item ${id}`, payload: lens ? { title: "t", lens } : { title: "t" } };
}

it("splits desk items into war and politics by lens, by day, newest first; unlensed pages stay out", () => {
  const arranged = arrangeNews([
    item(1, "2026-11-01T08:00:00Z", "security"),
    item(2, "2026-11-02T09:00:00Z", "political_stability"),
    item(3, "2026-11-02T07:00:00Z", "internal_stability"),
    item(4, "2026-11-02T10:00:00Z", "security"),
    item(5, "2026-10-26T10:00:00Z", null),
    item(6, "2026-11-02T06:00:00Z", "antisemitism"),
  ]);
  expect(arranged.war.map((day) => [day.day, day.items.map((i) => i.id)])).toEqual([["2026-11-02", [4]], ["2026-11-01", [1]]]);
  expect(arranged.politics.map((day) => [day.day, day.items.map((i) => i.id)])).toEqual([["2026-11-02", [2, 3]]]);
});

it("keeps only active countries with a desk", () => {
  const base: Tracker = { slug: "isr", title: "Israel", kind: "country_risk", status: "active", view: "globe", subject: { iso3: "ISR", desk: ["security"] }, observations: 0, latest_observation_at: null, level: null, level_rank: -1, latest_assessment: null };
  const shown = deskTrackers([base, { ...base, slug: "fra", subject: { iso3: "FRA" } }, { ...base, slug: "old", status: "paused" }, { ...base, slug: "ceg", kind: "stock" }]);
  expect(shown.map((t) => t.slug)).toEqual(["isr"]);
});

it("names a source by its domain", () => {
  expect(domainOf("https://www.timesofisrael.com/liveblog")).toBe("timesofisrael.com");
  expect(domainOf("not a url")).toBe("not a url");
});
