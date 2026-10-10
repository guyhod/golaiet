import { describe, expect, it } from "vitest";
import { formatWhen, hostOf } from "./api";

describe("formatWhen", () => {
  it("shows a dash for a missing time", () => {
    expect(formatWhen(null)).toBe("—");
    expect(formatWhen(undefined)).toBe("—");
  });
  it("renders day, month and time for a real one", () => {
    expect(formatWhen("2026-10-08T07:30:00Z")).toMatch(/8/);
  });
});

describe("hostOf", () => {
  it("drops the scheme, path and www", () => {
    expect(hostOf("https://www.reuters.com/world/x")).toBe("reuters.com");
  });
  it("returns an unparseable source as written", () => {
    expect(hostOf("telegram voice note")).toBe("telegram voice note");
  });
});
