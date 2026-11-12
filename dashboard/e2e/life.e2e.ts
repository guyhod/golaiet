import { expect, test } from "@playwright/test";

// Phase 4 at the screen: what Guy reports in Telegram is on the Life screen, a conversation opens it
// there, and the wall at /life keeps to life. Invented content: a stretching habit and a garden.
const TELEGRAM = process.env.E2E_TELEGRAM_URL ?? "http://127.0.0.1:8081";

async function outbound(): Promise<{ text: string }[]> {
  return (await fetch(`${TELEGRAM}/test/outbound`)).json();
}

async function say(text: string): Promise<string> {
  const before = (await outbound()).length;
  await fetch(`${TELEGRAM}/test/inbound`, { method: "POST", body: JSON.stringify({ text }) });
  await expect.poll(async () => (await outbound()).length, { timeout: 60_000 }).toBeGreaterThan(before);
  return (await outbound())[before].text;
}

test.describe.configure({ mode: "serial" });

test("a practice reported in chat counts on the Life screen", async ({ page }) => {
  // Whatever an earlier scenario left open on the screen is closed first.
  expect(await say("Show everything")).toBe("Showing everything.");
  expect(await say("Practice Stretching")).toBe("Stretching is a practice.");
  expect(await say("Did Stretching")).toBe("Recorded Stretching.");
  await page.goto("/");
  await page.getByRole("tab", { name: "Life" }).click();
  const tile = page.locator(".pulse", { hasText: "Stretching" });
  await expect(tile).toContainText("0 days since");
  await tile.click();
  await expect(page.getByRole("dialog")).toContainText("Did Stretching");
});

test("a lane is drawn on the map and stays off the list", async ({ page }) => {
  expect(await say("Lane Garden: Dig the beds")).toBe("Garden is a lane.");
  await page.goto("/");
  await page.getByRole("tab", { name: "Life" }).click();
  await expect(page.locator(".map-card")).toContainText("Dig the beds");
  await expect(page.locator(".map-card")).toContainText("0 / 1");
  await page.getByRole("tab", { name: "List" }).click();
  await expect(page.getByRole("button", { name: /Garden/ })).toHaveCount(0);
});

test("the wall shows life alone, and a conversation opens a lane on it", async ({ page }, testInfo) => {
  await page.goto("/life");
  await expect(page.getByRole("tablist")).toHaveCount(0);
  await expect(page.locator(".map-card")).toContainText("Garden");
  expect(await say("Show me Garden")).toBe("Garden is on screen.");
  const drawer = page.getByRole("dialog");
  await expect(drawer.getByRole("heading", { name: "Garden" })).toBeVisible();
  await expect(drawer).toContainText("Lane Garden: Dig the beds");
  await page.screenshot({ path: testInfo.outputPath("wall.png") });
  // The stream repeats the current focus on every connect; a reload does not open the drawer again.
  await page.reload();
  await expect(page.locator(".map-card")).toContainText("Garden");
  await page.waitForTimeout(2_000);
  await expect(drawer).toHaveCount(0);
  expect(await say("Show me Garden")).toBe("Garden is on screen.");
  await expect(drawer.getByRole("heading", { name: "Garden" })).toBeVisible();
  // A question about something that is not life does not take the wall away.
  expect(await say("Track Roses weekly")).toBe("Tracking Roses weekly.");
  expect(await say("Show me Roses")).toBe("Roses is on screen.");
  await expect(drawer.getByRole("heading", { name: "Garden" })).toBeVisible();
  await expect(page.locator(".map-card")).toBeVisible();
});
