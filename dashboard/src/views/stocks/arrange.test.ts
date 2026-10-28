import { expect, it } from "vitest";
import type { Tracker } from "../../api";
import { arrangeStocks } from "./arrange";

function stock(ticker: string, goodBelow: number, price: number | null, status: Tracker["status"] = "active"): Tracker {
  return {
    slug: ticker.toLowerCase(), title: ticker, kind: "stock", status, view: "price",
    subject: { ticker, good_below: goodBelow }, observations: 0, latest_observation_at: null,
    level: price === null ? null : price <= goodBelow ? "opportunity" : "watch", level_rank: 1,
    latest_assessment: price === null ? null : { id: 1, at: "2026-10-28T10:00:00Z", state: { price, good_below: goodBelow }, reason: "tick", evidence_ids: [] },
  };
}

const COUNTRY: Tracker = { ...stock("ISR", 1, null), kind: "country_risk", view: "globe" };

it("orders opportunities first, then by distance above the line, unticked last", () => {
  const shown = arrangeStocks([stock("MSFT", 300, 330), stock("CEG", 170, 165), stock("NEW", 50, null), stock("AAPL", 200, 210), COUNTRY, stock("OLD", 10, 5, "paused")]);
  expect(shown.map((s) => s.ticker)).toEqual(["CEG", "AAPL", "MSFT", "NEW"]);
  expect(shown[0].above).toBeCloseTo(-2.94, 2);
  expect(shown[1].above).toBeCloseTo(5, 5);
  expect(shown[3]).toMatchObject({ price: null, above: null, goodBelow: 50 });
});
