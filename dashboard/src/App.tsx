import { useEffect, useState } from "react";
import { getJson, watchFocus, formatWhen } from "./api";
import type { Alert, Focus, Health, Tracker } from "./api";
import { Module } from "./Module";
import { Overview } from "./views/Overview";
import { viewFor } from "./views";

/** The overview is always on screen. One tracker may be open over it, in its
 *  own view, as a module in the centre: a focus event from a conversation
 *  opens or closes it, and so does a click on a tile. */
export type Open = { slug: string; view: string; params: Record<string, unknown> } | null;

const REFRESH_MS = 60_000;
const ALERT_BANNER_HOURS = 24;

export function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [trackers, setTrackers] = useState<Tracker[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [focus, setFocus] = useState<Focus | null>(null);
  const [open, setOpen] = useState<Open>(null);
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

  useEffect(
    () =>
      watchFocus((pushed) => {
        setFocus(pushed);
        setOpen(pushed.tracker ? { slug: pushed.tracker, view: pushed.view, params: pushed.view_params } : null);
      }),
    [],
  );

  const recentAlert = alerts.find(
    (alert) => Date.now() - new Date(alert.created_at).getTime() < ALERT_BANNER_HOURS * 3600_000,
  );
  const View = open ? viewFor(open.view) : null;

  return (
    <div className="app">
      <header className="bar">
        <button className="brand" onClick={() => setOpen(null)}>
          Golaiet
        </button>
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

      <main>
        <Overview trackers={trackers} onOpen={(tracker) => setOpen({ slug: tracker.slug, view: tracker.view, params: {} })} />
      </main>

      {open && View && (
        <Module onClose={() => setOpen(null)}>
          <View slug={open.slug} params={open.params} onClose={() => setOpen(null)} />
        </Module>
      )}
    </div>
  );
}

function levelRankOf(trackers: Tracker[], alert: Alert): number {
  const tracker = trackers.find((candidate) => candidate.slug === alert.tracker);
  return tracker?.level_rank ?? 1;
}
