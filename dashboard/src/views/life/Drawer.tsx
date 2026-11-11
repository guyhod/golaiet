import type { ReactNode } from "react";
import type { TrackerDetail } from "../../api";
import { usePolled } from "../../polled";
import { Dots } from "./Panels";
import { dayOf, findLane, findStation, historyOf } from "./lookup";
import { fmt } from "./palette";
import type { Board, Campaign, Pulse, Selection, Station, StationState } from "./types";

// What opens on a click: the thing itself, then its History, the facts filed on its tracker in Guy's
// words, newest first. A station's history is the facts that name it or were cited when it changed.

const STATE_WORDS: Record<StationState, string> = {
  passed: "passed", current: "heading there now", ahead: "ahead", proposed: "proposed — not confirmed",
  decision: "decision", ref: "interchange",
};
// Enough for a lane's whole history; the API caps it at 500.
const HISTORY_ROWS = 500;

function Field({ name, value, alarm }: { name: string; value?: string | null; alarm?: boolean }) {
  if (!value) return null;
  return (
    <div className="field">
      <span className="field-name">{name}</span>
      <span className={alarm ? "alarm" : undefined}>{value}</span>
    </div>
  );
}

function Section({ title, count, children }: { title: string; count?: number; children: ReactNode }) {
  return (
    <section className="drawer-section">
      <h3>{title}{count !== undefined && <span className="count">{count}</span>}</h3>
      {children}
    </section>
  );
}

function History({ slug, station }: { slug: string; station?: string }) {
  const { data: detail, error } = usePolled<TrackerDetail>(`/api/trackers/${slug}?limit=${HISTORY_ROWS}`);
  if (error && !detail) return <Section title="History"><p className="none">Cannot load the history: {error}</p></Section>;
  if (!detail) return <Section title="History"><p className="none">Loading…</p></Section>;
  const facts = historyOf(detail.recent_observations, detail.recent_assessments, station);
  return (
    <Section title="History — what was recorded" count={facts.length}>
      {facts.length === 0 && <p className="none">Nothing recorded here yet.</p>}
      <ul className="history">
        {facts.map((fact) => (
          <li key={fact.id} className={fact.retracted ? "retracted" : undefined}>
            <span className="history-day">{dayOf(fact.observed_at)}</span>
            <span dir="auto">{fact.summary}{fact.retracted ? " (taken back)" : ""}</span>
          </li>
        ))}
      </ul>
    </Section>
  );
}

function StationBody({ lane, station, caption, onSelect }: { lane: Campaign; station: Station; caption?: string; onSelect: (selection: Selection) => void }) {
  return (
    <>
      <div className="crumb">
        <button className="link" onClick={() => onSelect({ kind: "lane", campaign: lane.id })}>{lane.title}</button>
        {caption ? ` › ${caption}` : ""}
      </div>
      <h2>{station.label}</h2>
      <div className="pills">
        <span className={`pill pill-${station.state}`}>{STATE_WORDS[station.state]}</span>
        {station.burning && <span className="pill pill-crit">burning</span>}
        {station.focus && <span className="pill pill-warn">focus</span>}
      </div>
      <div className="fields">
        <Field name="date" value={station.date && fmt(station.date)} />
        <Field name="check" value={station.check && fmt(station.check)} />
        <Field name="note" value={station.note} />
        <Field name="why" value={station.burning_why} alarm />
        <Field name="options" value={station.options?.join(" · ")} />
        <Field name="requires" value={station.requires?.join(", ")} />
        <Field name="ref" value={station.ref} />
      </div>
      <History slug={lane.id} station={station.id} />
    </>
  );
}

function LaneBody({ lane, onSelect }: { lane: Campaign; onSelect: (selection: Selection) => void }) {
  return (
    <>
      <h2>{lane.title}</h2>
      <div className="crumb">{lane._meta}</div>
      <div className="pills">
        {lane.focus && <span className="pill pill-warn">★ focus</span>}
        {lane.burning && <span className="pill pill-crit">! burning</span>}
      </div>
      <div className="fields">
        <Field name="focus" value={lane.focus_why} />
        <Field name="burning" value={lane.burning_why} alarm />
        <Field name="since" value={lane.burning_since} />
        <Field name="note" value={lane.note} />
        <Field name="path" value={lane.path} />
      </div>
      <Section title="Stations">
        {lane.tracks.map((track, position) => (
          <div key={position}>
            {track.caption && <div className="track-caption">{track.caption}</div>}
            <ul className="stations">
              {(track.stations ?? []).map((station) => (
                <li key={station.id}>
                  <button className={`station-row is-${station.state}`} onClick={() => onSelect({ kind: "station", campaign: lane.id, station: station.id })}>
                    <i className={`mark mark-${station.state}`} />
                    <span className="station-label">{station.label}</span>
                    <span className="station-when">
                      {station.state === "passed" && station.date ? fmt(station.date) : station.check ? `chk ${fmt(station.check)}` : ""}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </Section>
      <History slug={lane.id} />
    </>
  );
}

function PracticeBody({ tile }: { tile: Pulse }) {
  const events = [...tile.events].reverse();
  return (
    <>
      <h2>{tile.label}</h2>
      <div className={`practice-count state-${tile.state}`}><b>{tile.n}</b> {tile.unit}</div>
      <Dots dots={tile.dots} />
      <div className="fields">
        <Field name="rule" value={tile.color === "green" ? "a streak: a reported failure resets it" : "a gap: days since the last reported time"} />
        <Field name="since" value={fmt(tile.since)} />
        <Field name="note" value={tile.note} />
      </div>
      <Section title={tile.color === "green" ? "Reported failures" : "Reported events"} count={events.length}>
        {events.length === 0 && <p className="none">None recorded.</p>}
        <div className="pills">
          {events.map((day) => <span key={day} className={`pill ${tile.color === "green" ? "pill-crit" : "pill-passed"}`}>{fmt(day)}</span>)}
        </div>
      </Section>
      <History slug={tile.id} />
    </>
  );
}

export function Drawer({ selection, board, sheet, onClose, onSelect }: {
  selection: Selection; board: Board; sheet: boolean; onClose: () => void; onSelect: (selection: Selection) => void;
}) {
  let body: ReactNode;
  if (selection.kind === "practice") {
    const tile = board.pulse.find((candidate) => candidate.id === selection.id);
    body = tile ? <PracticeBody tile={tile} /> : <p className="none">This practice is off the board.</p>;
  } else {
    const lane = findLane(board, selection.campaign);
    const found = lane && selection.kind === "station" ? findStation(lane, selection.station) : undefined;
    if (lane && found) {
      body = <StationBody lane={lane} station={found.station} caption={found.track.caption} onSelect={onSelect} />;
    } else if (lane && selection.kind === "lane") {
      body = <LaneBody lane={lane} onSelect={onSelect} />;
    } else {
      // A lane the map has no room for, or one that is paused: its facts are still on record.
      body = (
        <>
          <p className="none">Not drawn on the map (a quiet lane).</p>
          <History slug={selection.campaign} station={selection.kind === "station" ? selection.station : undefined} />
        </>
      );
    }
  }
  return (
    <aside role="dialog" aria-label="details" className={`card drawer${sheet ? " sheet" : ""}`}>
      <button className="close" aria-label="close" onClick={onClose}>×</button>
      <div className="drawer-body">{body}</div>
    </aside>
  );
}
