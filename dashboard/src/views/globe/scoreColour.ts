/** A peace score's colour: 0 is the hot heat, 50 the warm one, 100 the calm one,
 *  blended linearly between the stops. Pure, so it is tested without a map. */
export type ScoreStops = { hot: string; warm: string; calm: string };

function channels(hex: string): [number, number, number] {
  const digits = hex.replace("#", "");
  const wide = digits.length === 3 ? digits.split("").map((d) => d + d).join("") : digits;
  return [0, 2, 4].map((at) => parseInt(wide.slice(at, at + 2), 16)) as [number, number, number];
}

function blend(from: string, to: string, share: number): string {
  const mixed = channels(from).map((a, i) => Math.round(a + (channels(to)[i] - a) * share));
  return "#" + mixed.map((c) => c.toString(16).padStart(2, "0")).join("");
}

export function scoreColour(score: number, stops: ScoreStops): string {
  const clamped = Math.max(0, Math.min(100, score));
  return clamped <= 50 ? blend(stops.hot, stops.warm, clamped / 50) : blend(stops.warm, stops.calm, (clamped - 50) / 50);
}
