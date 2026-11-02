import { expect, it } from "vitest";
import type { Observation, Tracker } from "../../api";
import { arrangeNews, dayOf, deskTrackers, domainOf, figureOf } from "./arrange";

function item(id: number, at: string, lens: string | null, url = `https://www.ynet.co.il/${id}`): Observation {
  return { id, observed_at: at, source_url: url, summary: `item ${id}`, payload: lens ? { title: "t", lens } : { title: "t" } };
}
function digest(id: number, at: string, lens: string, figure?: unknown): Observation {
  return { id, observed_at: at, source_url: "", summary: `digest ${id}`, payload: { lens, digest: true, ...(figure ? { figure } : {}) } };
}

it("gives each lens its latest digest and a week of items by local day, newest first; unlensed pages stay out", () => {
  const arranged = arrangeNews([
    item(1, "2026-11-01T08:00:00Z", "security"),
    item(2, "2026-11-02T09:00:00Z", "political_stability"),
    item(3, "2026-11-02T07:00:00Z", "internal_stability"),
    item(4, "2026-11-02T10:00:00Z", "security"),
    item(5, "2026-10-26T10:00:00Z", null),
    item(9, "2026-10-25T10:00:00Z", "security"),
    digest(6, "2026-11-01T06:30:00Z", "security"),
    digest(7, "2026-11-02T06:30:00Z", "security", { title: "f", bars: [{ label: "עזה", value: 3 }] }),
    digest(8, "2026-11-02T06:30:00Z", "political_stability", { title: "f", bars: [] }),
  ], new Date("2026-11-02T20:00:00Z"));
  const [war] = arranged.war;
  expect(war.lens).toBe("security");
  expect(war.digest?.id).toBe(7);
  expect(war.days.map((day) => [day.day, day.items.map((i) => i.id)])).toEqual([[dayOf("2026-11-02T10:00:00Z"), [4]], [dayOf("2026-11-01T08:00:00Z"), [1]]]);
  expect(arranged.politics.map((lens) => [lens.lens, lens.digest?.id ?? null, lens.days.flatMap((day) => day.items.map((i) => i.id))]))
    .toEqual([["political_stability", 8, [2]], ["internal_stability", null, [3]]]);
  expect(figureOf(war.digest)?.bars).toEqual([{ label: "עזה", value: 3 }]);
  expect(figureOf(arranged.politics[0].digest)).toBeNull();
  expect(figureOf(null)).toBeNull();
});

it("groups by the reader's calendar day", () => {
  const local = new Date(2026, 10, 2, 0, 0, 0);   // midnight on 2 November where the test runs
  expect(dayOf(local.toISOString())).toBe("2026-11-02");
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
