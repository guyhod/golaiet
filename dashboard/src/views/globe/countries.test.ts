import { describe, expect, it } from "vitest";
import { boundsOfCountry, countryShapes } from "./countries";

const RUSSIA = "643", FRANCE = "250", ANTARCTICA = "010";

function rings(numeric: string) {
  return countryShapes()
    .features.filter((shape) => shape.properties.numeric === numeric)
    .flatMap((shape) => (shape.geometry.type === "Polygon" ? [shape.geometry.coordinates] : shape.geometry.coordinates))
    .flat();
}

describe("countryShapes", () => {
  it("joins the world-atlas id to the ISO numeric the trackers carry", () => {
    expect(countryShapes().features.some((shape) => shape.properties.numeric === FRANCE)).toBe(true);
  });
  it("keeps a ring that crosses the antimeridian continuous", () => {
    for (const ring of rings(RUSSIA)) {
      for (let index = 1; index < ring.length; index++) {
        expect(Math.abs(ring[index][0] - ring[index - 1][0])).toBeLessThan(180);
      }
    }
  });
  it("leaves a ring that circles a pole alone", () => {
    const longitudes = rings(ANTARCTICA).flat().map(([longitude]) => longitude);
    expect(Math.min(...longitudes)).toBeGreaterThanOrEqual(-180);
    expect(Math.max(...longitudes)).toBeLessThanOrEqual(180);
  });
});

describe("boundsOfCountry", () => {
  it("frames the largest ring, so France is Europe and not French Guiana", () => {
    const [west, south, east, north] = boundsOfCountry(FRANCE)!;
    expect(west).toBeGreaterThan(-6);
    expect(east).toBeLessThan(10);
    expect(south).toBeGreaterThan(41);
    expect(north).toBeLessThan(52);
  });
  it("is null for a code the 50m file has no shape for", () => {
    expect(boundsOfCountry("000")).toBeNull();
  });
});
