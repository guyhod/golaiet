// What GET /api/life returns: the life board, built from the rows on every read.

export type StationState = "passed" | "current" | "ahead" | "proposed" | "decision" | "ref";

export interface Station {
  id: string;
  label: string;
  state: StationState;
  date?: string;
  check?: string;
  note?: string;
  rank?: number;
  burning?: boolean;
  burning_why?: string;
  burning_title?: string;
  focus?: boolean;
  focus_title?: string;
  options?: string[];
  requires?: string[];
  join?: "or" | "and";
  join_next?: "or" | "and";
  ref?: string; // "campaignId.stationId"
}

export interface Track {
  caption?: string;
  mini?: boolean;
  stations?: Station[];
}

export interface Campaign {
  id: string;
  title: string;
  short: string;
  check?: string;
  target_by?: string;
  note?: string;
  focus?: boolean;
  focus_rank?: number;
  focus_why?: string;
  burning?: boolean;
  burning_since?: string;
  burning_why?: string;
  layout?: "wide" | "card";
  path?: string;
  tracks: Track[];
  _wide: boolean;
  _meta: string;
}

export interface Pulse {
  id: string;
  label: string;
  color: "green" | "red";
  n: number;
  since: string;
  note: string;
  events: string[];
  unit: string;
  sub: string;
  dots: ("ok" | "bad" | "none")[];
  state: "good" | "warn" | "bad";
}

export interface Burning {
  title: string;
  since: string;
  why: string;
  path: string;
  rank: number;
  campaign: string;
  station?: string;
}

export interface Focus {
  title: string;
  why: string;
  rank: number;
  campaign: string;
  station?: string;
}

export interface NextAction {
  text: string;
  source: string;
  hot: boolean;
}

export interface HorizonItem {
  label: string;
  kind: "check" | "target";
  campaign: string;
  station?: string;
}

export interface HorizonDay {
  date: string; // YYYY-MM-DD
  label: string; // "Sep 21" / "Sep 18 · today"
  today: boolean;
  items: HorizonItem[];
}

export interface TrailItem {
  at: string;
  date: string;
  label: string;
  campaign: string; // the lane's short name
  station: string;
}

export interface Board {
  today: string; // YYYY-MM-DD
  pulse: Pulse[];
  burning: Burning[];
  burning_more: number;
  focus: Focus[];
  focus_more: number;
  horizon: HorizonDay[];
  trail: TrailItem[];
  next: NextAction[];
  lanes: Campaign[];
  quiet: string[];
}

/** What is open in the drawer. */
export type Selection =
  | { kind: "station"; campaign: string; station: string }
  | { kind: "lane"; campaign: string }
  | { kind: "practice"; id: string };
