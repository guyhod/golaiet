import { useEffect, useState } from "react";
import { getJson, watchFocus, formatWhen } from "./api";
import type { Alert, Focus, Health, Tracker } from "./api";
import { Module } from "./Module";
import { Globe } from "./views/Globe";
import { Overview } from "./views/Overview";
import { Stocks } from "./views/Stocks";
import { viewFor } from "./views";

/** The screen is the globe (the default), the stocks or the list of tiles; the
 *  bar switches them. A country tracker opens on the globe, its kind's view;
 *  any other tracker opens in its own view as a module over the screen. A focus event
 *  from a conversation opens or closes either, and so does a click on a tile. */
export type Open = { slug: string; view: string; params: Record<string, unknown> } | null;
type Screen = "globe" | "stocks" | "list";
const SCREENS: [Screen, string][] = [["globe", "Globe"], ["stocks", "Stocks"], ["list", "List"]];

const REFRESH_MS = 60_000;
const ALERT_BANNER_HOURS = 24;

export function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [trackers, setTrackers] = useState<Tracker[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [focus, setFocus] = useState<Focus | null>(null);
  const [open, setOpen] = useState<Open>(null);
  const [screen, setScreen] = useState<Screen>("globe");
  const [picked, setPicked] = useState<string | null>(null);
  const [refreshedAt, setRefreshedAt] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const refresh = async () => {
      try {
        const [healthNow, trackersNow, alertsNow] = await Promise.all([
          getJson<Health>("/api/health"),
          getJson<Tracker[]>("/api/trackers"),
          getJson<Alert[]>("/api/alerts?limit=5"),
        ]);
        if (cancelled) return;
        setHealth(healthNow);
        setTrackers(trackersNow);
        setAlerts(alertsNow);
        setRefreshedAt(new Date());
        setError(null);
      } catch (failure) {
        if (!cancelled) setError(String(failure));
      }
    };
    refresh();
    const timer = setInterval(refresh, REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  const show = (slug: string | null, view: string, params: Record<string, unknown>) => {
    if (slug && view === "globe") {
      setScreen("globe");
      setPicked(slug);
      setOpen(null);
    } else {
      setOpen(slug ? { slug, view, params } : null);
      if (!slug) setPicked(null);
    }
  };

  useEffect(
    () =>
      watchFocus((pushed) => {
        setFocus(pushed);
        show(pushed.tracker, pushed.view, pushed.view_params);
      }),
    [],
  );

  const recentAlert = alerts.find(
    (alert) => Date.now() - new Date(alert.created_at).getTime() < ALERT_BANNER_HOURS * 3600_000,
  );
  const view = open ? viewFor(open.view) : null;

  return (
    <div className="app">
      <header className="bar">
        <button className="brand" onClick={() => setOpen(null)}>
          Golaiet
        </button>
        <nav className="tabs" role="tablist" aria-label="screen">
          {SCREENS.map(([choice, word]) => (
            <button key={choice} role="tab" aria-selected={screen === choice} className={screen === choice ? "on" : ""} onClick={() => setScreen(choice)}>
              {word}
            </button>
          ))}
        </nav>
        <span className="muted">
          {health ? `heartbeat ${formatWhen(health.last_heartbeat)}` : "connecting…"}
          {refreshedAt ? ` · screen ${formatWhen(refreshedAt.toISOString())}` : ""}
        </span>
        {focus?.note && open && <span className="note">{focus.note}</span>}
      </header>

      {health?.status === "stale" && (
        <div className="banner stale">
          No heartbeat since {formatWhen(health.last_heartbeat)}. The scheduler is not running; what you see may be old.
        </div>
      )}
      {error && <div className="banner stale">Cannot reach the API: {error}</div>}
      {recentAlert && (
        <div className={`banner alert lvl-${levelRankOf(trackers, recentAlert)}`}>
          🔔 {recentAlert.text} <span className="muted">· {formatWhen(recentAlert.created_at)}</span>
        </div>
      )}

      {screen === "globe" ? (
        <main className="full"><Globe shown={picked} onShow={setPicked} /></main>
      ) : screen === "stocks" ? (
        <main><Stocks trackers={trackers} onOpen={(tracker) => show(tracker.slug, tracker.view, {})} /></main>
      ) : (
        <main><Overview trackers={trackers} onOpen={(tracker) => show(tracker.slug, tracker.view, {})} /></main>
      )}

      {open && view && (
        <Module wide={view.wide} onClose={() => setOpen(null)}>
          <view.component slug={open.slug} params={open.params} onClose={() => setOpen(null)} />
        </Module>
      )}
    </div>
  );
}

function levelRankOf(trackers: Tracker[], alert: Alert): number {
  const tracker = trackers.find((candidate) => candidate.slug === alert.tracker);
  return tracker?.level_rank ?? 1;
}
