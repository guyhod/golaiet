import { useEffect, useMemo, useRef, useState } from "react";
import type { Map as MapLibreMap, MapLayerMouseEvent } from "maplibre-gl";
import type { Tracker, TrackerDetail } from "../api";
import { getJson, formatWhen, hostOf } from "../api";
import type { ViewProps } from "./index";
import { boundsOfCountry } from "./globe/countries";
import { createMap, fillLayerId, fitWorld, flyToCountry, paint, select } from "./globe/createMap";

const REFRESH_MS = 60_000;

/** A country tracker's assessment state, as the country_risk kind records it. */
type Conflict = {
  title: string; kind: string; scope: string; heat: string; summary: string; detail: string; parties: string[];
  since?: string; place?: { name: string; kind: string; latitude: number; longitude: number } | null;
  counterpart_iso3?: string | null; source_urls: string[];
};
type CountryState = {
  level: string; peace_score: number; peace_score_reason: string; overview: string; outlook: string;
  conflicts: Conflict[]; trend?: string; peace_score_change?: number;
};

// Copies HEAT_DEFINITIONS in core/kinds/country_risk.py: the legend has to say
// what the agent was told each heat means. Change them together.
const LEGEND: [rank: number, word: string, meaning: string][] = [
  [4, "hot", "organized violence in the last 30 days, or imminent"],
  [3, "warm", "violence with casualties in the last 12 months, or active mobilization"],
  [2, "cold", "tension without violence in the last 12 months"],
  [1, "dormant", "frozen or historic, no activity in over a year, could reignite"],
  [0, "calm", "researched, no conflicts"],
  [-1, "no data", "no tracker for this country"],
];

/** The globe painted by every country tracker's level, with one country's record beside it. */
export function Globe({ slug, onClose }: ViewProps) {
  const [countries, setCountries] = useState<Tracker[]>([]);
  const [shown, setShown] = useState(slug);
  const [detail, setDetail] = useState<TrackerDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [map, setMap] = useState<MapLibreMap | null>(null);
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
    paint(map, countries.map((country) => ({ numeric: String(country.subject.numeric), level_rank: country.level_rank })));
  }, [map, countries]);

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
        <ul className="legend">
          {LEGEND.map(([rank, word, meaning]) => (
            <li key={word} className={`lvl-${rank}`}><span className="swatch" />{word} <span className="muted">{meaning}</span></li>
          ))}
        </ul>
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
                    {state.trend === "improving" ? "▲" : state.trend === "worsening" ? "▼" : "●"} {state.trend}
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
              <span className="section-label">Conflicts · {state.conflicts.length}</span>
              {state.conflicts.map((conflict) => <ConflictCard key={conflict.title} conflict={conflict} byIso3={countries} />)}
              {!state.conflicts.length && <p className="muted">No conflicts recorded.</p>}
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

function ConflictCard({ conflict, byIso3 }: { conflict: Conflict; byIso3: Tracker[] }) {
  const [open, setOpen] = useState(false);
  const counterpart = byIso3.find((tracker) => tracker.subject.iso3 === conflict.counterpart_iso3)?.title ?? conflict.counterpart_iso3;
  return (
    <article className={`conflict lvl-${HEAT_RANK[conflict.heat] ?? -1}`}>
      <button className="conflict-title" onClick={() => setOpen(!open)}>{conflict.title}</button>
      <div className="small">
        <span className="level">{conflict.heat}</span> · {conflict.kind.replace("_", " ")} · {conflict.scope}
        {conflict.place && <> · {conflict.place.name}</>}
      </div>
      <p className="small">{conflict.summary}</p>
      {open && (
        <div className="conflict-detail small">
          <p>{conflict.detail}</p>
          <p className="muted">
            Parties: {conflict.parties.join(", ")}
            {conflict.since && <> · since {conflict.since}</>}
            {counterpart && <> · counterpart {counterpart}</>}
          </p>
          <ul className="sources">
            {conflict.source_urls.map((url) => <li key={url}><a href={url} target="_blank" rel="noreferrer">{hostOf(url)}</a></li>)}
          </ul>
        </div>
      )}
    </article>
  );
}
