import { useEffect, useMemo, useState } from "react";
import type { PricePoint, TrackerDetail } from "../api";
import { getJson, formatWhen } from "../api";
import { Chart, echarts, paletteOf } from "../chart";
import { LineChart } from "echarts/charts";
import { Observations } from "./Observations";
import { priceOption } from "./price/option";
import type { ViewProps } from "./index";

echarts.use([LineChart]);

const REFRESH_MS = 60_000;
const DAYS = 30;

/** A stock: the price line against the good-below line, the current level, and the news filed against the thesis. */
export function Price({ slug, onClose }: ViewProps) {
  const [detail, setDetail] = useState<TrackerDetail | null>(null);
  const [points, setPoints] = useState<PricePoint[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      Promise.all([
        getJson<TrackerDetail>(`/api/trackers/${slug}?sourced=true&limit=50`),
        getJson<PricePoint[]>(`/api/trackers/${slug}/prices?days=${DAYS}`),
      ])
        .then(([loaded, ticks]) => !cancelled && (setDetail(loaded), setPoints(ticks), setError(null)))
        .catch((failure) => !cancelled && setError(String(failure)));
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [slug]);

  const goodBelow = Number(detail?.subject.good_below ?? 0);
  const levelRank = detail?.level_rank ?? -1;
  const option = useMemo(
    () => (points && detail ? priceOption(points, goodBelow, paletteOf(levelRank)) : null),
    [points, detail, goodBelow, levelRank],
  );

  if (error) return <p className="empty">Cannot load {slug}: {error}</p>;
  if (!detail || !points) return <p className="empty">Loading {slug}…</p>;
  const last = points[points.length - 1];
  const judged = detail.latest_assessment;

  return (
    <div className={`price lvl-${levelRank}`}>
      <div className="chart-pane">
        <div className="feed-head">
          <h1>{detail.title}</h1>
          <span className="ticker muted">{String(detail.subject.ticker)}</span>
          <span className="level">{detail.level ?? "unjudged"}</span>
        </div>
        <div className="price-figures">
          <span className="figure">{last ? last.price.toFixed(2) : "—"}</span>
          <span className="muted">last {last ? formatWhen(last.at) : "never"} · good below {goodBelow.toFixed(2)}</span>
        </div>
        {option && <Chart className="chart" option={option} />}
        {!points.length && <p className="muted small">No ticks yet: the first lands within 15 minutes of New York's open.</p>}
      </div>
      <aside className="record">
        <button className="close" onClick={onClose} aria-label="close">×</button>
        <span className="section-label">Thesis</span>
        <p className="brief">{detail.brief}</p>
        {judged && (
          <section className="judgment">
            <div className="muted small">judged {formatWhen(judged.at)}</div>
            <p>{judged.reason}</p>
          </section>
        )}
        <span className="section-label">News</span>
        <Observations observations={detail.recent_observations} empty="No news filed yet; the daily session files what bears on the thesis." />
      </aside>
    </div>
  );
}

