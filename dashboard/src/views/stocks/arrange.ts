// The stocks screen's order: pure, so Vitest covers it.
import type { Tracker } from "../../api";

export type Stock = {
  tracker: Tracker;
  ticker: string;
  goodBelow: number;
  /** The last tick's price, from the judgment the tick wrote; null before the first tick. */
  price: number | null;
  /** How far the price sits above the line, in percent; negative at or below it. Null before the first tick. */
  above: number | null;
};

/** Every active stock tracker, opportunities first, then the nearest to its line; unticked ones last. */
export function arrangeStocks(trackers: Tracker[]): Stock[] {
  return trackers
    .filter((tracker) => tracker.kind === "stock" && tracker.status === "active")
    .map((tracker) => {
      const goodBelow = Number(tracker.subject.good_below);
      const state = tracker.latest_assessment?.state ?? {};
      const price = typeof state.price === "number" ? state.price : null;
      return { tracker, ticker: String(tracker.subject.ticker), goodBelow, price,
        above: price === null ? null : ((price - goodBelow) / goodBelow) * 100 };
    })
    .sort((a, b) => (a.above ?? Infinity) - (b.above ?? Infinity) || a.ticker.localeCompare(b.ticker));
}
