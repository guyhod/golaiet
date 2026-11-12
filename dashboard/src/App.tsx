import { useEffect, useState } from "react";
import { watchFocus, formatWhen } from "./api";
import type { Alert, Focus, Health, Tracker } from "./api";
import { usePolled } from "./polled";
import { Module } from "./Module";
import { firstTime } from "./pushed";
import { Globe } from "./views/Globe";
import { Life, type Pushed } from "./views/life/Life";
import { News } from "./views/News";
import { Overview } from "./views/Overview";
import { Stocks } from "./views/Stocks";
import { viewFor } from "./views";

/** The screen is the globe (the default), the stocks, the news room, Guy's life or the list of tiles; the
 *  bar switches them. A country tracker opens on the globe and a practice or a campaign on the Life
 *  screen, their kinds' views; any other tracker opens in its own view as a module over the screen. A
 *  focus event from a conversation opens or closes either, and so does a click on a tile.
 *
 *  At /life the app is the wall: the Life screen alone, with no bar to leave it by. A focus pushed about
 *  a tracker of another kind is ignored there, so a question about a stock never takes the wall away. */
export type Open = { slug: string; view: string; params: Record<string, unknown> } | null;
type Screen = "globe" | "stocks" | "news" | "life" | "list";
const SCREENS: [Screen, string][] = [["globe", "Globe"], ["stocks", "Stocks"], ["news", "News"], ["life", "Life"], ["list", "List"]];
const LIFE_VIEW = "campaign_map";
const WALL = window.location.pathname.replace(/\/$/, "") === "/life";

const ALERT_BANNER_HOURS = 24;

export function App() {
  const polledHealth = usePolled<Health>("/api/health");
  const polledTrackers = usePolled<Tracker[]>("/api/trackers");
  const polledAlerts = usePolled<Alert[]>("/api/alerts?limit=5");
  const health = polledHealth.data;
  const trackers = polledTrackers.data ?? [];
  const alerts = polledAlerts.data ?? [];
  const refreshedAt = polledTrackers.at;
  const error = polledHealth.error ?? polledTrackers.error ?? polledAlerts.error;
  const [focus, setFocus] = useState<Focus | null>(null);
  const [open, setOpen] = useState<Open>(null);
  const [screen, setScreen] = useState<Screen>(WALL ? "life" : "globe");
  const [picked, setPicked] = useState<string | null>(null);
  const [pushedLife, setPushedLife] = useState<Pushed | null>(null);

  const show = (slug: string | null, view: string, params: Record<string, unknown>) => {
    if (WALL) {
      return;
    } else if (slug && view === "globe") {
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
        if (pushed.tracker && pushed.view === LIFE_VIEW) {
          // The stream repeats the current focus on every connect; a drawer is opened for it once.
          if (!firstTime(pushed.set_at)) return;
          setScreen("life");
          setPushedLife({ slug: pushed.tracker, params: pushed.view_params, at: pushed.set_at });
          setOpen(null);
        } else {
          show(pushed.tracker, pushed.view, pushed.view_params);
        }
      }),
    [],
  );

  const recentAlert = alerts.find(
    (alert) => Date.now() - new Date(alert.created_at).getTime() < ALERT_BANNER_HOURS * 3600_000,
  );
  const view = open ? viewFor(open.view) : null;

  const banners = (
    <>
      {health?.status === "stale" && (
        <div className="banner stale">
          No heartbeat since {formatWhen(health.last_heartbeat)}. The scheduler is not running; what you see may be old.
        </div>
      )}
      {error && <div className="banner stale">Cannot reach the API: {error}</div>}
    </>
  );
  if (WALL) {
    return (
      <div className="app">
        {banners}
        <Life wall pushed={pushedLife} />
      </div>
    );
  }

  return (
    <div className="app">
      <header className="bar">
        <button className="brand" onClick={() => setOpen(null)}>
          Golaiet
        </button>
        <nav className="tabs" role="tablist" aria-label="screen">
          {SCREENS.map(([choice, word]) => (
            <button key={choice} role="tab" aria-selected={screen === choice} className={screen === choice ? "on" : ""} onClick={() => { setScreen(choice); setPushedLife(null); }}>
              {word}
            </button>
          ))}
        </nav>
        <span className="muted">
          {health ? `heartbeat ${formatWhen(health.last_heartbeat)}` : "connecting…"}
          {refreshedAt ? ` · screen ${formatWhen(refreshedAt.toISOString())}` : ""}
        </span>
        <a className="admin-link muted" href="/admin/">Admin</a>
        {focus?.note && open && <span className="note">{focus.note}</span>}
      </header>

      {banners}
      {recentAlert && (
        <div className={`banner alert lvl-${levelRankOf(trackers, recentAlert)}`}>
          🔔 {recentAlert.text} <span className="muted">· {formatWhen(recentAlert.created_at)}</span>
        </div>
      )}

      {screen === "globe" ? (
        <main className="full"><Globe shown={picked} onShow={setPicked} /></main>
      ) : screen === "stocks" ? (
        <main><Stocks trackers={trackers} onOpen={(tracker) => show(tracker.slug, tracker.view, {})} /></main>
      ) : screen === "news" ? (
        <main><News trackers={trackers} /></main>
      ) : screen === "life" ? (
        <Life wall={false} pushed={pushedLife} />
      ) : (
        // Life trackers have their own screen; as tiles they would bury the list under stations.
        <main><Overview trackers={trackers.filter((tracker) => tracker.view !== LIFE_VIEW)} onOpen={(tracker) => show(tracker.slug, tracker.view, {})} /></main>
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
