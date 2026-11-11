// The life map's palette and geometry. The map is drawn in SVG with these values as attributes, so they
// are constants here and not CSS tokens; the panels around it take the same colours from the .life tokens.
export const PAGE = "#0d0d0d";
export const PANEL = "#1a1a19";
export const BORDER = "rgba(255,255,255,0.10)";
export const INK = "#ffffff";
export const INK2 = "#c3c2b7";
export const MUTED = "#898781";
export const GRID = "#2c2c2a";
export const AXIS = "#383835";
export const GOOD = "#0ca30c";
export const WARN = "#fab219";
export const SERIOUS = "#ec835a";
export const CRIT = "#d03b3b";
export const CURRENT = "#3987e5";

export const MAP_W = 1230;
export const LANE_H = 64;
export const TRACK_H = 62;

/** "Sep 18": how the board writes a day. */
export function fmt(iso: string): string {
  const d = new Date(iso.slice(0, 10) + "T00:00:00");
  return d.toLocaleDateString("en-US", { month: "short" }) + " " + d.getDate();
}

/** A label on at most two lines of about `width` characters, with an ellipsis on the second. */
export function wrap(label: string, width = 15): string[] {
  const words = String(label).split(/\s+/).filter(Boolean);
  const lines: string[] = [];
  let cur = "";
  for (const w of words) {
    if (cur && cur.length + 1 + w.length > width) {
      lines.push(cur);
      cur = w;
    } else {
      cur = (cur + " " + w).trim();
    }
  }
  if (cur) lines.push(cur);
  return lines.length <= 2 ? lines : [lines[0], lines.slice(1).join(" ").slice(0, width - 1) + "…"];
}

export function stateColor(state: "good" | "warn" | "bad"): string {
  return state === "good" ? GOOD : state === "warn" ? WARN : CRIT;
}
