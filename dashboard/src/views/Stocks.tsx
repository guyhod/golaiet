import { useEffect, useMemo, useState } from "react";
import type { PricePoint, Tracker } from "../api";
import { getJson, formatWhen } from "../api";
import { Chart, echarts, paletteOf } from "../chart";
import { LineChart } from "echarts/charts";
import { priceOption } from "./price/option";
import { arrangeStocks, type Stock } from "./stocks/arrange";

echarts.use([LineChart]);

const REFRESH_MS = 60_000;
const DAYS = 30;

/** Every stock as a card: the price against its line and the last 30 days; a click opens the price view. */
export function Stocks({ trackers, onOpen }: { trackers: Tracker[]; onOpen: (tracker: Tracker) => void }) {
  const stocks = useMemo(() => arrangeStocks(trackers), [trackers]);
  if (!stocks.length) {
    return <p className="empty">No stock tracked yet. Say “track CEG, good below 170” in Telegram.</p>;
  }
  return (
    <div className="stocks">
      {stocks.map((stock) => <StockCard key={stock.tracker.slug} stock={stock} onOpen={() => onOpen(stock.tracker)} />)}
    </div>
  );
}

function StockCard({ stock, onOpen }: { stock: Stock; onOpen: () => void }) {
  const { tracker, ticker, goodBelow, price, above } = stock;
  const [points, setPoints] = useState<PricePoint[]>([]);
  useEffect(() => {
    let cancelled = false;
    const load = () =>
      getJson<PricePoint[]>(`/api/trackers/${tracker.slug}/prices?days=${DAYS}`)
        .then((ticks) => !cancelled && setPoints(ticks))
        .catch(() => undefined);   // the card's figures stand without the chart
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => { cancelled = true; clearInterval(timer); };
  }, [tracker.slug]);
  const option = useMemo(() => (points.length ? priceOption(points, goodBelow, paletteOf(tracker.level_rank)) : null), [points, goodBelow, tracker.level_rank]);
  return (
    <article className={`stock lvl-${tracker.level_rank}`}>
      <button className="stock-head" onClick={onOpen}>
        <span className="ticker">{ticker}</span>
        <span className="title">{tracker.title}</span>
        <span className="level">{tracker.level ?? "unjudged"}</span>
      </button>
      <div className="price-figures">
        <span className="figure">{price === null ? "—" : price.toFixed(2)}</span>
        <span className="muted small">
          good below {goodBelow.toFixed(2)}
          {above !== null && <> · {above <= 0 ? "at the line" : `${above.toFixed(1)}% above`}</>}
          {tracker.latest_assessment && <> · {formatWhen(tracker.latest_assessment.at)}</>}
        </span>
      </div>
      {option ? <Chart className="chart" option={option} /> : <p className="muted small">No ticks yet: the first lands within 15 minutes of New York's open.</p>}
    </article>
  );
}
