import type { Observation } from "../api";
import { formatDay, hostOf } from "../api";

/** Observations newest first, each with its date, source and payload; the ones a judgment relied on are marked. */
export function Observations({ observations, evidenceIds = [], empty = "Nothing observed yet." }:
  { observations: Observation[]; evidenceIds?: number[]; empty?: string }) {
  return (
    <ol className="observations">
      {observations.map((observation) => (
        <li key={observation.id} className={evidenceIds.includes(observation.id) ? "evidence" : ""}>
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
      {!observations.length && <li className="muted">{empty}</li>}
    </ol>
  );
}
