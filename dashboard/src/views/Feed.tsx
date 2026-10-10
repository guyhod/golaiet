import { useEffect, useState } from "react";
import type { TrackerDetail } from "../api";
import { getJson, formatDay, formatWhen, hostOf } from "../api";
import type { ViewProps } from "./index";

const REFRESH_MS = 60_000;

/** The generic view: latest judgment on top, then the observations with their sources. */
export function Feed({ slug, onBack }: ViewProps) {
  const [detail, setDetail] = useState<TrackerDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      getJson<TrackerDetail>(`/api/trackers/${slug}?limit=50`)
        .then((loaded) => !cancelled && (setDetail(loaded), setError(null)))
        .catch((failure) => !cancelled && setError(String(failure)));
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [slug]);

  if (error) return <p className="empty">Cannot load {slug}: {error}</p>;
  if (!detail) return <p className="empty">Loading {slug}…</p>;
  const judged = detail.latest_assessment;

  return (
    <article className="feed">
      <div className="feed-head">
        <button className="back" onClick={onBack}>← all</button>
        <h1>{detail.title}</h1>
        <span className={`level lvl-${detail.level_rank}`}>{detail.level ?? "unjudged"}</span>
      </div>
      <p className="brief">{detail.brief}</p>

      <section className={`judgment lvl-${detail.level_rank}`}>
        {judged ? (
          <>
            <div className="muted small">
              judged {formatWhen(judged.at)}
              {judged.state.score != null ? ` · score ${judged.state.score}` : ""}
              {judged.evidence_ids.length ? ` · on ${judged.evidence_ids.length} observations` : ""}
            </div>
            <p>{judged.reason}</p>
          </>
        ) : (
          <p className="muted">No judgment yet; the first assess run writes one.</p>
        )}
      </section>

      <ol className="observations">
        {detail.recent_observations.map((observation) => (
          <li key={observation.id} className={judged?.evidence_ids.includes(observation.id) ? "evidence" : ""}>
            <div className="when">{formatDay(observation.observed_at)}</div>
            <div>
              <p>{observation.summary}</p>
              <div className="muted small">
                {observation.source_url && (
                  <a href={observation.source_url} target="_blank" rel="noreferrer">{hostOf(observation.source_url)}</a>
                )}
                {Object.entries(observation.payload)
                  .filter(([, value]) => value != null && value !== "")
                  .map(([key, value]) => (
                    <span key={key} className="chip">{key}: {String(value)}</span>
                  ))}
              </div>
            </div>
          </li>
        ))}
        {!detail.recent_observations.length && <li className="muted">Nothing observed yet.</li>}
      </ol>
    </article>
  );
}
