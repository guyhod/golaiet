// What /api returns, and how the app reads it. The dashboard decides nothing:
// it draws what the database says.

export type Assessment = {
  id: number;
  at: string;
  state: { level?: string; score?: number };
  reason: string;
  evidence_ids: number[];
};

export type Observation = {
  id: number;
  observed_at: string;
  source_url: string;
  summary: string;
  payload: Record<string, string | number | null>;
};

export type Tracker = {
  slug: string;
  title: string;
  kind: string;
  status: "active" | "paused" | "archived";
  view: string;
  observations: number;
  latest_observation_at: string | null;
  level: string | null;
  level_rank: number;
  latest_assessment: Assessment | null;
};

export type TrackerDetail = Tracker & {
  brief: string;
  recent_assessments: Assessment[];
  recent_observations: Observation[];
};

export type Alert = {
  id: number;
  tracker: string;
  level: string;
  text: string;
  created_at: string;
  delivered_at: string | null;
};

export type Focus = {
  tracker: string | null;
  view: string;
  view_params: Record<string, unknown>;
  note: string;
  set_at: string;
};

export type Health = {
  status: "ok" | "stale";
  last_heartbeat: string | null;
  telegram_configured: boolean;
  trackers: number;
};

export async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return response.json() as Promise<T>;
}

/** Hold the focus stream open; the browser's EventSource reconnects on its own. */
export function watchFocus(onFocus: (focus: Focus) => void): () => void {
  const source = new EventSource("/api/focus/stream");
  source.addEventListener("focus", (event) => onFocus(JSON.parse((event as MessageEvent).data)));
  return () => source.close();
}

export function formatWhen(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  return date.toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function formatDay(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}
