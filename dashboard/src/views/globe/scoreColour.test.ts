import { describe, expect, it } from "vitest";
import { scoreColour } from "./scoreColour";

const stops = { hot: "#ff0000", warm: "#ff8800", calm: "#00ff00" };

describe("scoreColour", () => {
  it("hits the stops at 0, 50 and 100", () => {
    expect(scoreColour(0, stops)).toBe("#ff0000");
    expect(scoreColour(50, stops)).toBe("#ff8800");
    expect(scoreColour(100, stops)).toBe("#00ff00");
  });
  it("blends between neighbouring stops", () => {
    expect(scoreColour(25, stops)).toBe("#ff4400");
    expect(scoreColour(75, stops)).toBe("#80c400");
  });
  it("clamps out-of-range scores", () => {
    expect(scoreColour(-5, stops)).toBe("#ff0000");
    expect(scoreColour(140, stops)).toBe("#00ff00");
  });
});
