import { useMemo } from "react";
import type { Tracker, TrackerDetail } from "../api";
import { hostOf } from "../api";
import { Chart, echarts, paletteOf } from "../chart";
import { BarChart } from "echarts/charts";
import { usePolled } from "../polled";
import { arrangeNews, COLUMNS, deskTrackers, figureOf, LENS_HE, type Day, type LensNews } from "./news/arrange";
import { figureOption } from "./news/figure";

echarts.use([BarChart]);

const ROWS = 200;
const HEBREW = "he-IL";

/** The news room, in Hebrew: every country with a desk, war and politics side by side. Israel's is the first. */
export function News({ trackers }: { trackers: Tracker[] }) {
  const desks = useMemo(() => deskTrackers(trackers), [trackers]);
  if (!desks.length) {
    return <p className="empty" dir="rtl" lang="he">אין עדיין דסק חדשות. בקש בטלגרם: "עקוב אחרי הביטחון והפוליטיקה בישראל כל יום".</p>;
  }
  return (
    <div className="news" dir="rtl" lang="he">
      {desks.map((tracker) => <Desk key={tracker.slug} tracker={tracker} />)}
    </div>
  );
}

function Desk({ tracker }: { tracker: Tracker }) {
  const detail = usePolled<TrackerDetail>(`/api/trackers/${tracker.slug}?limit=${ROWS}`).data;
  const arranged = useMemo(() => arrangeNews(detail?.recent_observations ?? []), [detail]);
  return (
    <section className="desk">
      <h1>{countryName(tracker)}</h1>
      <div className="columns">
        {COLUMNS.map((column) => (
          <div key={column.key} className="column">
            <h2>{column.title}</h2>
            {arranged[column.key].map((lens) => <Lens key={lens.lens} news={lens} levelRank={tracker.level_rank} />)}
          </div>
        ))}
      </div>
    </section>
  );
}

function Lens({ news, levelRank }: { news: LensNews; levelRank: number }) {
  const figure = figureOf(news.digest);
  const option = useMemo(() => (figure ? figureOption(figure, paletteOf(levelRank)) : null), [figure, levelRank]);
  return (
    <div className="lens-news">
      <h3>{LENS_HE[news.lens] ?? news.lens}</h3>
      {news.digest ? (
        <article className="digest">
          <p>{news.digest.summary}</p>
          {figure && option && (
            <div className="figure">
              <h4>{figure.title}</h4>
              <Chart className="chart" option={option} />
              {figure.bars.some((bar) => bar.note) && (
                <ul className="notes">
                  {figure.bars.filter((bar) => bar.note).map((bar) => <li key={bar.label}><b>{bar.label}</b> · {bar.note}</li>)}
                </ul>
              )}
            </div>
          )}
          <span className="muted small">תמונת מצב · {formatDay(news.digest.observed_at)}</span>
        </article>
      ) : (
        <p className="muted small">עדיין אין תמונת מצב: הדסק רץ כל בוקר ב־06:30.</p>
      )}
      {news.days.length > 0 && <h4 className="muted">מקורות</h4>}
      {news.days.map((day) => <DayList key={day.day} day={day} />)}
    </div>
  );
}

function DayList({ day }: { day: Day }) {
  return (
    <div className="day">
      <h5>{formatDay(day.day)}</h5>
      {day.items.map((item) => (
        <article key={item.id} className="item">
          <p>{item.summary}</p>
          <span className="muted small">
            <a href={item.source_url} target="_blank" rel="noreferrer">{hostOf(item.source_url)}</a>
            {" · "}{formatTime(item.observed_at)}
          </span>
        </article>
      ))}
    </div>
  );
}

function countryName(tracker: Tracker): string {
  const iso2 = tracker.subject.iso2;
  const named = typeof iso2 === "string" ? new Intl.DisplayNames([HEBREW], { type: "region" }).of(iso2) : undefined;
  return named ?? tracker.title;
}

function formatDay(iso: string): string {
  const stamp = iso.length === 10 ? `${iso}T12:00:00` : iso;
  return new Date(stamp).toLocaleDateString(HEBREW, { weekday: "long", day: "numeric", month: "long" });
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(HEBREW, { hour: "2-digit", minute: "2-digit" });
}

