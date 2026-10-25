import { useState } from "react";
import type { Tracker } from "../api";
import { arrowOf, formatWhen } from "../api";
import { arrange, levelsOf, SORTS, trendOf, type SortBy } from "./overview/arrange";

/** Every active tracker as a tile; chips pick a level, the control picks the order. */
export function Overview({ trackers, onOpen }: { trackers: Tracker[]; onOpen: (tracker: Tracker) => void }) {
  const [sort, setSort] = useState<SortBy>("level");
  const [level, setLevel] = useState<string | null>(null);
  const shown = arrange(trackers, sort, level);
  if (!trackers.some((tracker) => tracker.status === "active")) {
    return <p className="empty">Nothing is tracked yet. Say “track …” in Telegram.</p>;
  }
  return (
    <>
      <div className="controls">
        <div className="chips" role="radiogroup" aria-label="level">
          <button role="radio" aria-checked={level === null} className={`chip${level === null ? " on" : ""}`} onClick={() => setLevel(null)}>all</button>
          {levelsOf(trackers).map(({ level: word, rank }) => (
            <button key={word} role="radio" aria-checked={level === word} className={`chip lvl-${rank}${level === word ? " on" : ""}`} onClick={() => setLevel(word)}>
              {word}
            </button>
          ))}
        </div>
        <label className="muted">
          order{" "}
          <select value={sort} onChange={(event) => setSort(event.target.value as SortBy)}>
            {SORTS.map(([value, word]) => <option key={value} value={value}>{word}</option>)}
          </select>
        </label>
      </div>
      {!shown.length && <p className="empty">No tracker at this level.</p>}
      <div className="tiles">
        {shown.map((tracker) => {
          const trend = trendOf(tracker);
          return (
            <button key={tracker.slug} className={`tile lvl-${tracker.level_rank}`} onClick={() => onOpen(tracker)}>
              <div className="tile-head">
                <span>
                  <span className="level">{tracker.level ?? "unjudged"}</span>
                  {trend && <span className={`trend trend-${trend.word}`}> {arrowOf(trend.word)} {trend.change > 0 ? "+" : ""}{trend.change}</span>}
                </span>
                <span className="muted">{tracker.kind}</span>
              </div>
              <h2>{tracker.title}</h2>
              <p className="reason">{tracker.latest_assessment?.reason ?? "No judgment yet."}</p>
              <div className="muted small">
                {tracker.observations} observations · last {formatWhen(tracker.latest_observation_at)}
              </div>
            </button>
          );
        })}
      </div>
    </>
  );
}
