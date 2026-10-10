import type { Tracker } from "../api";
import { formatWhen } from "../api";

/** Every active tracker as a tile, hottest first. */
export function Overview({ trackers, onOpen }: { trackers: Tracker[]; onOpen: (tracker: Tracker) => void }) {
  const active = trackers
    .filter((tracker) => tracker.status === "active")
    .sort(
      (a, b) =>
        b.level_rank - a.level_rank ||
        (b.latest_observation_at ?? "").localeCompare(a.latest_observation_at ?? ""),
    );
  if (!active.length) return <p className="empty">Nothing is tracked yet. Say “track …” in Telegram.</p>;
  return (
    <div className="tiles">
      {active.map((tracker) => (
        <button key={tracker.slug} className={`tile lvl-${tracker.level_rank}`} onClick={() => onOpen(tracker)}>
          <div className="tile-head">
            <span className="level">{tracker.level ?? "unjudged"}</span>
            <span className="muted">{tracker.kind}</span>
          </div>
          <h2>{tracker.title}</h2>
          <p className="reason">{tracker.latest_assessment?.reason ?? "No judgment yet."}</p>
          <div className="muted small">
            {tracker.observations} observations · last {formatWhen(tracker.latest_observation_at)}
          </div>
        </button>
      ))}
    </div>
  );
}
