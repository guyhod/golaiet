import type { CSSProperties } from "react";
import type { Burning, Focus, HorizonDay, NextAction, Pulse, Selection, TrailItem } from "./types";

// The panels around the life map: the pulse row of practices, what is burning, where the focus is, the
// week ahead, the next actions and what passed. Each item opens the drawer on what it names.

type Select = (selection: Selection) => void;
type Placed = { style?: CSSProperties };

function placeOf(item: { campaign: string; station?: string }): Selection {
  return item.station ? { kind: "station", campaign: item.campaign, station: item.station } : { kind: "lane", campaign: item.campaign };
}

export function Dots({ dots }: { dots: Pulse["dots"] }) {
  return (
    <div className="dots" aria-label="last 14 days">
      {dots.map((dot, position) => <i key={position} className={`dot dot-${dot}`} />)}
    </div>
  );
}

export function PulseTile({ tile, selected, onSelect }: { tile: Pulse; selected: boolean; onSelect: Select }) {
  return (
    <button className={`card pulse state-${tile.state}${selected ? " selected" : ""}`} onClick={() => onSelect({ kind: "practice", id: tile.id })}>
      <span className="pulse-label"><b>{tile.color === "green" ? "✓" : "◔"}</b> {tile.label}</span>
      <span className="pulse-count"><b>{tile.n}</b> {tile.unit}</span>
      <Dots dots={tile.dots} />
      <span className="pulse-sub">{tile.sub}</span>
    </button>
  );
}

export function PulseRow({ pulse, selectedId, onSelect }: { pulse: Pulse[]; selectedId?: string; onSelect: Select }) {
  return (
    <div className="pulse-row">
      {pulse.map((tile) => <PulseTile key={tile.id} tile={tile} selected={selectedId === tile.id} onSelect={onSelect} />)}
    </div>
  );
}

export function BurningPanel({ items, more, style, onSelect }: { items: Burning[]; more: number; onSelect: Select } & Placed) {
  return (
    <section className="card panel burning" style={style}>
      <h3>Burning — what slipped</h3>
      <ul>
        {items.length === 0 && <li className="none">Nothing burning.</li>}
        {items.map((item, position) => (
          <li key={position}>
            <button className="row" onClick={() => onSelect(placeOf(item))}>
              <span className="badge-number">{position + 1}</span>
              <span className="row-text">
                <span className="row-title">{item.title}</span>
                <span className="row-detail">
                  <b>{item.since}</b>{item.since && item.why ? " · " : ""}{item.why} <span className="path">{item.path}</span>
                </span>
              </span>
            </button>
          </li>
        ))}
        {more > 0 && <li className="none">+{more} more burning</li>}
      </ul>
    </section>
  );
}

export function FocusPanel({ items, style, onSelect }: { items: Focus[]; onSelect: Select } & Placed) {
  return (
    <section className="card panel focus" style={style}>
      <h3>Focus — where attention goes now</h3>
      <ul>
        {items.length === 0 && <li className="none">No focus set.</li>}
        {items.map((item, position) => (
          <li key={position}>
            <button className="row" onClick={() => onSelect(placeOf(item))}>
              <span className="star">★</span>
              <span className="row-text">
                <span className="row-title">{item.title}</span>
                <span className="row-detail">{item.why}</span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function HorizonBar({ horizon, filterDate, style, onFilter, onSelect }: {
  horizon: HorizonDay[]; filterDate: string | null; onFilter: (date: string | null) => void; onSelect: Select;
} & Placed) {
  return (
    <section className="card horizon" style={style}>
      <h3>Horizon · 7 days</h3>
      <div className="horizon-days">
        {horizon.length === 0 && <span>nothing dated in the next 7 days</span>}
        {horizon.map((day) => {
          const active = filterDate === day.date;
          return (
            <span key={day.date} className={`horizon-day${filterDate && !active ? " dimmed" : ""}`}>
              <button className={`pill${active ? " pill-warn" : day.today ? " pill-current" : ""}`}
                title={active ? "clear filter" : "show only what is due this day"} onClick={() => onFilter(active ? null : day.date)}>
                {day.label}{active ? " ×" : ""}
              </button>
              <span>
                {day.items.map((item, position) => (
                  <span key={position}>
                    {position > 0 && " · "}
                    <button className="link" onClick={() => onSelect(placeOf(item))}>{item.label}</button>
                  </span>
                ))}
              </span>
            </span>
          );
        })}
      </div>
    </section>
  );
}

export function NextPanel({ next, trail, filterLabel, style, onClearFilter, onSource }: {
  next: NextAction[]; trail: TrailItem[]; filterLabel: string | null; onClearFilter: () => void;
  onSource: (source: string, station?: string) => void;
} & Placed) {
  return (
    <section className="card panel next" style={style}>
      <h3>
        Next action — the stolen ten minutes
        {filterLabel && <button className="pill pill-warn" onClick={onClearFilter}>{filterLabel} ×</button>}
      </h3>
      <ul>
        {next.length === 0 && <li className="none">Nothing written for this day.</li>}
        {next.map((action, position) => (
          <li key={position} className="row">
            <span className={`ring${action.hot ? " hot" : ""}`}>{action.hot ? "!" : "○"}</span>
            <span className="row-text">
              <span className="next-text">{action.text}</span>
              <button className="link source" onClick={() => onSource(action.source)}>{action.source}</button>
            </span>
          </li>
        ))}
      </ul>
      <h3 className="passed">Passed — last 14 days</h3>
      <ul>
        {trail.length === 0 && <li className="none">Nothing passed in the last 14 days.</li>}
        {trail.map((item, position) => (
          <li key={position} className="row">
            <span className="trail-date">{item.date}</span>
            <span className="row-text">
              <span className="trail-label">{item.label}</span>
              <button className="link source" onClick={() => onSource(item.campaign, item.station)}>{item.campaign}</button>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function Legend({ quiet, style }: { quiet: string[] } & Placed) {
  return (
    <footer className="legend-row" style={style}>
      <span><i className="mark mark-passed" />passed</span>
      <span><i className="mark mark-current" />heading there now</span>
      <span><i className="mark mark-ahead" />ahead</span>
      <span><i className="mark mark-proposed" />proposed — not confirmed</span>
      <span>◇ decision</span>
      <span><i className="edge" />all required (AND)</span>
      <span><i className="edge edge-or" />any one (OR)</span>
      <span className="quiet">
        {quiet.length ? `${quiet.length} quiet lane${quiet.length === 1 ? "" : "s"}: ${quiet.join(" · ")}` : "all lanes shown"}
      </span>
    </footer>
  );
}
