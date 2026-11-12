import { expect, it } from "vitest";
import { firstTime } from "./pushed";

function store(kept: Record<string, string> = {}) {
  return { getItem: (key: string) => kept[key] ?? null, setItem: (key: string, value: string) => void (kept[key] = value) };
}

it("a pushed focus is acted on once, across reconnects and reloads", () => {
  const kept = store();
  expect(firstTime("2031-03-08T08:22:00Z", kept)).toBe(true);
  expect(firstTime("2031-03-08T08:22:00Z", kept)).toBe(false);
  // A reload: the page's own memory is gone, the browser's is not.
  expect(firstTime("2031-03-08T08:22:00Z", store({ "golaiet.focus.handled": "2031-03-08T08:22:00Z" }))).toBe(false);
  expect(firstTime("2031-03-09T10:00:00Z", kept)).toBe(true);
  // With nowhere to keep it, it is still once per load.
  expect(firstTime("2031-03-10T10:00:00Z", null)).toBe(true);
  expect(firstTime("2031-03-10T10:00:00Z", null)).toBe(false);
});
