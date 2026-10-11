import { describe, expect, it } from "vitest";
import { priceOption } from "./option";

const palette = { text: "#fff", muted: "#888", line: "#333", panel: "#111", level: "#2563eb" };

describe("priceOption", () => {
  it("draws every tick and the good-below line in the level's colour", () => {
    const option = priceOption([{ at: "2026-10-12T14:30:00Z", price: 172.1 }, { at: "2026-10-12T14:45:00Z", price: 168.4 }], 170, palette);
    const [series] = option.series as Array<{ data: unknown[]; lineStyle: { color: string }; markLine: { data: Array<{ yAxis: number }> } }>;
    expect(series.data).toEqual([["2026-10-12T14:30:00Z", 172.1], ["2026-10-12T14:45:00Z", 168.4]]);
    expect(series.lineStyle.color).toBe("#2563eb");
    expect(series.markLine.data).toEqual([{ yAxis: 170 }]);
  });
  it("keeps the line in frame when prices sit far from it", () => {
    const axis = priceOption([{ at: "2026-10-12T14:30:00Z", price: 250 }], 170, palette).yAxis as { min: number; max: number };
    expect(axis.min).toBeLessThan(170);
    expect(axis.max).toBeGreaterThan(250);
  });
  it("frames the line alone when there are no ticks yet", () => {
    const axis = priceOption([], 170, palette).yAxis as { min: number; max: number };
    expect(axis.min).toBeLessThan(170);
    expect(axis.max).toBeGreaterThan(170);
  });
});
