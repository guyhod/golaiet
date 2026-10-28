import { expect, it } from "vitest";
import { viewFor } from "./index";

it("every kind gets feed unless it names a known view", () => {
  expect(viewFor("price").wide).toBe(true);
  expect(viewFor("feed").wide).toBe(false);
  expect(viewFor("no-such-view")).toBe(viewFor("feed"));
});
