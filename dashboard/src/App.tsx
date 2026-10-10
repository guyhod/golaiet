import { useEffect, useState } from "react";
import { getJson, watchFocus, formatWhen } from "./api";
import type { Alert, Focus, Health, Tracker } from "./api";
import { Overview } from "./views/Overview";
import { viewFor } from "./views";

/** What the screen shows: the overview, or one tracker in a view. A focus
 *  event from a conversation sets it; a click on a tile sets it locally. */
export type Screen = { kind: "overview" } | { kind: "tracker"; slug: string; view: string; params: Record<string, unknown> };

const REFRESH_MS = 60_000;
const ALERT_BANNER_HOURS = 24;

export function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [trackers, setTrackers] = useState<Tracker[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [focus, setFocus] = useState<Focus | null>(null);
  const [screen, setScreen] = useState<Screen>({ kind: "overview" });
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
        setScreen(
          pushed.tracker
            ? { kind: "tracker", slug: pushed.tracker, view: pushed.view, params: pushed.view_params }
            : { kind: "overview" },
        );
      }),
    [],
  );

  const recentAlert = alerts.find(
    (alert) => Date.now() - new Date(alert.created_at).getTime() < ALERT_BANNER_HOURS * 3600_000,
  );
  const View = screen.kind === "tracker" ? viewFor(screen.view) : null;

  return (
    <div className="app">
      <header className="bar">
        <button className="brand" onClick={() => setScreen({ kind: "overview" })}>
          Golaiet
        </button>
        <span className="muted">
          {health ? `heartbeat ${formatWhen(health.last_heartbeat)}` : "connecting…"}
          {refreshedAt ? ` · screen ${formatWhen(refreshedAt.toISOString())}` : ""}
        </span>
        {focus?.note && screen.kind === "tracker" && <span className="note">{focus.note}</span>}
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
        {screen.kind === "overview" || !View ? (
          <Overview
            trackers={trackers}
            onOpen={(tracker) => setScreen({ kind: "tracker", slug: tracker.slug, view: tracker.view, params: {} })}
          />
        ) : (
          <View slug={screen.slug} params={screen.params} onBack={() => setScreen({ kind: "overview" })} />
        )}
      </main>
    </div>
  );
}

function levelRankOf(trackers: Tracker[], alert: Alert): number {
  const tracker = trackers.find((candidate) => candidate.slug === alert.tracker);
  return tracker?.level_rank ?? 1;
}
