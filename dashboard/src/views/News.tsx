import { useEffect, useMemo, useState } from "react";
import type { Observation, Tracker, TrackerDetail } from "../api";
import { getJson, formatWhen } from "../api";
import { arrangeNews, COLUMNS, deskTrackers, domainOf, type Day } from "./news/arrange";

const REFRESH_MS = 60_000;
const ITEMS = 200;

/** The news room: every country with a desk, its items in two columns. Israel's is the first. */
export function News({ trackers }: { trackers: Tracker[] }) {
  const desks = useMemo(() => deskTrackers(trackers), [trackers]);
  if (!desks.length) {
    return <p className="empty">No news desk yet. Say “follow Israel's security and politics daily” in Telegram.</p>;
  }
  return (
    <div className="news">
      {desks.map((tracker) => <Desk key={tracker.slug} tracker={tracker} />)}
    </div>
  );
}

function Desk({ tracker }: { tracker: Tracker }) {
  const [items, setItems] = useState<Observation[]>([]);
  useEffect(() => {
    let cancelled = false;
    const load = () =>
      getJson<TrackerDetail>(`/api/trackers/${tracker.slug}?sourced=true&limit=${ITEMS}`)
        .then((detail) => !cancelled && setItems(detail.recent_observations))
        .catch(() => undefined);   // the last load stands until the next
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => { cancelled = true; clearInterval(timer); };
  }, [tracker.slug]);
  const arranged = useMemo(() => arrangeNews(items), [items]);
  return (
    <section className="desk">
      <h1>{tracker.title}</h1>
      <div className="columns">
        {COLUMNS.map((column) => (
          <div key={column.key} className="column">
            <h2>{column.title}</h2>
            {arranged[column.key].length
              ? arranged[column.key].map((day) => <DayList key={day.day} day={day} manyLenses={column.lenses.length > 1} />)
              : <p className="muted small">Nothing filed yet: the desk runs every morning at 06:30.</p>}
          </div>
        ))}
      </div>
    </section>
  );
}

function DayList({ day, manyLenses }: { day: Day; manyLenses: boolean }) {
  return (
    <div className="day">
      <h3>{formatDay(day.day)}</h3>
      {day.items.map((item) => (
        <article key={item.id} className="item">
          <p>{item.summary}</p>
          <span className="muted small">
            {manyLenses && <>{String(item.payload.lens).replace("_", " ")} · </>}
            <a href={item.source_url} target="_blank" rel="noreferrer">{domainOf(item.source_url)}</a>
            {" · "}{formatWhen(item.observed_at)}
          </span>
        </article>
      ))}
    </div>
  );
}

function formatDay(day: string): string {
  return new Date(`${day}T12:00:00`).toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" });
}
