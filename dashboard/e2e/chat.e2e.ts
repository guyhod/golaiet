import { expect, test } from "@playwright/test";

// Phase 1's exit tests, repeatable: a message from Guy goes through the
// poller, the reply job, the (fake) CLI, the tool server, the database, the
// API and the stream, and the screen and Telegram show the result.
const TELEGRAM = process.env.E2E_TELEGRAM_URL ?? "http://127.0.0.1:8081";

type Sent = { chat_id: number | string; text: string };

async function outbound(): Promise<Sent[]> {
  return (await fetch(`${TELEGRAM}/test/outbound`)).json();
}

/** Send one message as Guy and return what the bot answered. */
async function say(text: string): Promise<string> {
  const before = (await outbound()).length;
  await fetch(`${TELEGRAM}/test/inbound`, { method: "POST", body: JSON.stringify({ text }) });
  await expect.poll(async () => (await outbound()).length, { timeout: 60_000 }).toBeGreaterThan(before);
  return (await outbound())[before].text;
}

test.describe.configure({ mode: "serial" });

test("track X in chat makes a tile on the screen", async ({ page }) => {
  expect(await say("Track VRAM supply weekly")).toBe("Tracking VRAM supply weekly.");
  await page.goto("/");
  await expect(page.getByRole("button", { name: /VRAM supply/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /VRAM supply/ })).toContainText("unjudged");
});

test("show me X opens it over the stream, show everything closes it", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(await say("Show me VRAM supply")).toBe("VRAM supply is on screen.");
  await expect(page.getByRole("dialog").getByRole("heading", { name: "VRAM supply" })).toBeVisible();
  expect(await say("Show everything")).toBe("Showing everything.");
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("a level change reaches Telegram once and lands in the banner", async ({ page }) => {
  expect(await say("Mark VRAM supply elevated")).toBe("VRAM supply is now elevated.");
  await expect.poll(async () => (await outbound()).map((sent) => sent.text)).toContain(
    "🔔 VRAM supply: quiet → elevated. Marked by the end-to-end test.",
  );
  await page.goto("/");
  await expect(page.locator(".banner.alert")).toContainText("VRAM supply: quiet → elevated");
  await expect(page.getByRole("button", { name: /VRAM supply/ })).toContainText("elevated");

  // The same level again is not news: no second alert.
  expect(await say("Mark VRAM supply elevated")).toBe("VRAM supply is now elevated.");
  const alerts = (await outbound()).filter((sent) => sent.text.startsWith("🔔"));
  expect(alerts).toHaveLength(1);
});
