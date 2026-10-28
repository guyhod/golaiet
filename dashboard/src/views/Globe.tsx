import { useEffect, useMemo, useRef, useState } from "react";
import type { Map as MapLibreMap, MapLayerMouseEvent } from "maplibre-gl";
import type { Tracker, TrackerDetail } from "../api";
import { arrowOf, getJson, formatWhen, hostOf } from "../api";
import type { ViewProps } from "./index";
import { boundsOfCountry } from "./globe/countries";
import { createMap, fillLayerId, fitWorld, flyToCountry, paint, select, type ColourBy } from "./globe/createMap";

const REFRESH_MS = 60_000;

/** A country tracker's assessment state, as the country_risk kind records it. */
type Lens = { heat: string; summary: string; detail: string; latest_event?: string | null; source_urls: string[]; held_until?: string };
type CountryState = {
  level: string; peace_score: number; peace_score_reason: string; overview: string; outlook: string;
  // Absent on records judged before 2026-10-28, which filed a conflict list instead; they stand until the next run.
  lenses?: Record<string, Lens>; trend?: string; peace_score_change?: number;
};

// Copies LENSES in core/kinds/country_risk.py: the six things judged for every
// country, in the record's order. Change them together.
export const LENSES: [key: string, word: string][] = [
  ["security", "security"],
  ["internal_stability", "internal stability"],
  ["political_stability", "political stability"],
  ["antisemitism", "antisemitism"],
  ["islam", "Islam"],
  ["migration", "migration"],
];

// Copies HEAT_DEFINITIONS in core/kinds/country_risk.py: the legend has to say
// what the agent was told each heat means. Change them together.
const LEGEND: [rank: number, word: string, meaning: string][] = [
  [4, "hot", "organized violence in the last 30 days, or imminent"],
  [3, "warm", "violence with casualties in the last 12 months, or active mobilization"],
  [2, "cold", "tension without violence in the last 12 months"],
  [1, "dormant", "frozen or historic, no activity in over a year, could reignite"],
  [0, "calm", "nothing of the kind in the last 12 months"],
  [-1, "no data", "no tracker for this country"],
];
// Copies TREND_STEP in core/kinds/country_risk.py: a trend is the peace score
// against the previous judgment, five points either way. Change them together.
const TREND_LEGEND: [word: string, meaning: string][] = [
  ["improving", "peace score up 5 or more since the previous judgment"],
  ["stable", "within 5 points"],
  ["worsening", "down 5 or more"],
  ["none", "one judgment so far, or no tracker"],
];
const COLOUR_BY: [ColourBy, string][] = [["level", "hottest conflict"], ["score", "peace score"], ["trend", "trend"]];

/** The globe painted by every country tracker's level, with one country's record beside it. */
export function Globe({ slug, onClose }: ViewProps) {
  const [countries, setCountries] = useState<Tracker[]>([]);
  const [shown, setShown] = useState(slug);
  const [detail, setDetail] = useState<TrackerDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [map, setMap] = useState<MapLibreMap | null>(null);
  const [colourBy, setColourBy] = useState<ColourBy>("level");
  const byNumeric = useMemo(
    () => new Map(countries.map((country) => [String(country.subject.numeric), country])),
    [countries],
  );
  const byNumericRef = useRef(byNumeric);
  byNumericRef.current = byNumeric;

  useEffect(() => setShown(slug), [slug]);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      getJson<Tracker[]>("/api/trackers")
        .then((all) => !cancelled && setCountries(all.filter((tracker) => tracker.kind === "country_risk")))
        .catch((failure) => !cancelled && setError(String(failure)));
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => { cancelled = true; clearInterval(timer); };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setDetail(null);
    const load = () =>
      getJson<TrackerDetail>(`/api/trackers/${shown}?limit=100`)
        .then((loaded) => !cancelled && (setDetail(loaded), setError(null)))
        .catch((failure) => !cancelled && setError(String(failure)));
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => { cancelled = true; clearInterval(timer); };
  }, [shown]);

  useEffect(() => {
    const created = createMap(containerRef.current!);
    created.once("load", () => setMap(created));
    const onResize = () => fitWorld(created);
    created.on("resize", onResize);
    return () => { created.remove(); setMap(null); };
  }, []);

  useEffect(() => {
    if (!map) return;
    paint(map, countries.map((country) => ({
      numeric: String(country.subject.numeric), level_rank: country.level_rank,
      peace_score: (country.latest_assessment?.state as CountryState | undefined)?.peace_score ?? null,
      trend: (country.latest_assessment?.state as CountryState | undefined)?.trend ?? null,
    })), colourBy);
  }, [map, countries, colourBy]);

  useEffect(() => {
    if (!map) return;
    const onClick = (event: MapLayerMouseEvent) => {
      const numeric = event.features?.[0]?.properties.numeric;
      const tracker = typeof numeric === "string" ? byNumericRef.current.get(numeric) : undefined;
      if (tracker) setShown(tracker.slug);
    };
    const onMove = (event: MapLayerMouseEvent) => {
      const numeric = event.features?.[0]?.properties.numeric;
      map.getCanvas().style.cursor = typeof numeric === "string" && byNumericRef.current.has(numeric) ? "pointer" : "";
    };
    map.on("click", fillLayerId, onClick);
    map.on("mousemove", fillLayerId, onMove);
    return () => { map.off("click", fillLayerId, onClick); map.off("mousemove", fillLayerId, onMove); };
  }, [map]);

  useEffect(() => {
    if (!map || !detail) return;
    const numeric = String(detail.subject.numeric);
    select(map, numeric);
    const bounds = boundsOfCountry(numeric);
    if (bounds) flyToCountry(map, bounds);
  }, [map, detail]);

  const state = detail?.latest_assessment?.state as CountryState | undefined;

  return (
    <div className="globe">
      <div className="globe-map">
        <div ref={containerRef} className="globe-canvas" />
        <div className="legend">
          <div className="colour-by" role="radiogroup" aria-label="colour by">
            {COLOUR_BY.map(([choice, word]) => (
              <button key={choice} role="radio" aria-checked={colourBy === choice} className={colourBy === choice ? "on" : ""} onClick={() => setColourBy(choice)}>
                {word}
              </button>
            ))}
          </div>
          {colourBy === "level" ? (
            <ul>
              {LEGEND.map(([rank, word, meaning]) => (
                <li key={word} className={`lvl-${rank}`}><span className="swatch" />{word} <span className="muted">{meaning}</span></li>
              ))}
            </ul>
          ) : colourBy === "trend" ? (
            <ul>
              {TREND_LEGEND.map(([word, meaning]) => (
                <li key={word} className={`trend-${word}`}><span className="swatch" />{word} <span className="muted">{meaning}</span></li>
              ))}
            </ul>
          ) : (
            <div className="score-scale">
              <div className="score-gradient" />
              <div className="score-ends muted"><span>0 · at war</span><span>50</span><span>100 · at peace</span></div>
              <div className="muted">how peaceful the country is as a whole, judged with the conflicts</div>
            </div>
          )}
        </div>
      </div>
      <aside className="record">
        <div className="feed-head">
          <h1>{detail?.title ?? shown}</h1>
          <span className={`level lvl-${detail?.level_rank ?? -1}`}>{detail?.level ?? "unjudged"}</span>
          <button className="close" onClick={onClose} aria-label="close">×</button>
        </div>
        {error && <p className="empty">{error}</p>}
        {detail && !state && <p className="muted">No judgment yet; the first research run writes one.</p>}
        {detail && state && (
          <>
            <section className="score">
              <div className="score-head">
                <div><span className="section-label">Peace score</span><div className="score-value">{state.peace_score}<span className="muted">/100</span></div></div>
                {state.trend && (
                  <span className={`trend trend-${state.trend}`}>
                    {arrowOf(state.trend)} {state.trend}
                    {state.peace_score_change ? ` (${state.peace_score_change > 0 ? "+" : ""}${state.peace_score_change})` : ""}
                  </span>
                )}
              </div>
              <div className="score-bar"><div style={{ width: `${state.peace_score}%` }} /></div>
              <p>{state.peace_score_reason}</p>
              <div className="muted small">judged {formatWhen(detail.latest_assessment!.at)}</div>
            </section>
            <section><span className="section-label">Overview</span><p>{state.overview}</p></section>
            <section><span className="section-label">Outlook · 12–24 months</span><p>{state.outlook}</p></section>
            <section>
              <span className="section-label">Lenses</span>
              {state.lenses
                ? LENSES.map(([key, word]) => state.lenses![key] && <LensCard key={key} word={word} lens={state.lenses![key]} />)
                : <p className="muted">Judged before the lenses; the next run fills them.</p>}
            </section>
            <section>
              <span className="section-label">Sources · {detail.recent_observations.length}</span>
              <ul className="sources">
                {detail.recent_observations.map((observation) => (
                  <li key={observation.id}>
                    <a href={observation.source_url} target="_blank" rel="noreferrer">{String(observation.payload.title ?? hostOf(observation.source_url))}</a>
                    <span className="muted small"> {hostOf(observation.source_url)} · {formatWhen(observation.observed_at)}</span>
                  </li>
                ))}
              </ul>
            </section>
          </>
        )}
      </aside>
    </div>
  );
}

const HEAT_RANK: Record<string, number> = { calm: 0, dormant: 1, cold: 2, warm: 3, hot: 4 };

function LensCard({ word, lens }: { word: string; lens: Lens }) {
  const [open, setOpen] = useState(false);
  return (
    <article className={`lens lvl-${HEAT_RANK[lens.heat] ?? -1}`}>
      <button className="lens-title" onClick={() => setOpen(!open)}>{word}</button>
      <div className="small">
        <span className="level">{lens.heat}</span>
        {lens.latest_event && <> · latest event {lens.latest_event}</>}
        {lens.held_until && <span className="muted"> · held until {lens.held_until}</span>}
      </div>
      <p className="small">{lens.summary}</p>
      {open && (
        <div className="lens-detail small">
          <p>{lens.detail}</p>
          <ul className="sources">
            {lens.source_urls.map((url) => <li key={url}><a href={url} target="_blank" rel="noreferrer">{hostOf(url)}</a></li>)}
          </ul>
        </div>
      )}
    </article>
  );
}
