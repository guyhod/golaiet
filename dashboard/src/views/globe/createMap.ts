// The globe: MapLibre with the globe projection and an inline style (no tiles,
// no glyphs), painted by each country tracker's level. Ported and trimmed from
// the conflict map's frontend/src/map/createMap.ts.
import { Map as MapLibreMap, setWorkerUrl, type ExpressionSpecification, type FilterSpecification } from "maplibre-gl";
// MapLibre 6 looks for its worker next to its own module, which no longer exists
// once Vite has bundled it; ?worker&url bundles it with its chunk.
import maplibreWorkerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import "maplibre-gl/dist/maplibre-gl.css";
import { countryShapes, type Bounds } from "./countries";

setWorkerUrl(maplibreWorkerUrl);

const SOURCE = "countries";
const FILL = "country-fill";
const SELECTED = "country-selected";
const WORLD_CENTER: [number, number] = [35, 30];
const FOCUS_MAX_ZOOM = 6;
const FLY_MS = 900;

export type Painted = { numeric: string; level_rank: number };

// Colours live only in styles.css; a missing token throws instead of hiding behind a default.
function token(name: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  if (!value) throw new Error(`CSS custom property ${name} is not defined on :root`);
  return value;
}

function countryFilter(numerics: string[]): FilterSpecification {
  return ["in", ["get", "numeric"], ["literal", numerics]];
}

function fillColour(painted: Painted[]): string | ExpressionSpecification {
  const none = token("--heat-none");
  const pairs: [string[], string][] = [];
  for (const rank of [0, 1, 2, 3, 4]) {
    const numerics = painted.filter((country) => country.level_rank === rank).map((country) => country.numeric);
    if (numerics.length) pairs.push([numerics, token(`--heat-${rank}`)]);
  }
  if (!pairs.length) return none;
  const [[firstNumerics, firstColour], ...rest] = pairs;
  return ["match", ["get", "numeric"], firstNumerics, firstColour, ...rest.flat(), none];
}

// The zoom at which the globe fills most of the shorter side of its container.
function worldZoom(map: MapLibreMap): number {
  const { clientWidth, clientHeight } = map.getContainer();
  const diameter = 0.9 * Math.min(clientWidth, clientHeight);
  const focalLength = clientHeight / 2 / Math.tan((map.getVerticalFieldOfView() * Math.PI) / 360);
  const radius = (diameter * (diameter + Math.hypot(diameter, 2 * focalLength))) / (4 * focalLength);
  return Math.log2((2 * Math.PI * radius * Math.cos((WORLD_CENTER[1] * Math.PI) / 180)) / 512);
}

export function fitWorld(map: MapLibreMap) {
  map.jumpTo({ center: WORLD_CENTER, zoom: worldZoom(map) });
}

export function createMap(container: HTMLElement): MapLibreMap {
  const water = token("--map-water");
  const map = new MapLibreMap({
    container,
    attributionControl: false,
    style: {
      version: 8,
      projection: { type: "globe" },
      sources: { [SOURCE]: { type: "geojson", data: countryShapes() } },
      layers: [
        { id: "water", type: "background", paint: { "background-color": water } },
        { id: FILL, type: "fill", source: SOURCE, paint: { "fill-color": token("--heat-none"), "fill-opacity": 1 } },
        { id: "country-border", type: "line", source: SOURCE, paint: { "line-color": water, "line-width": 0.8 } },
        { id: "selected-casing", type: "line", source: SOURCE, filter: countryFilter([]), paint: { "line-color": water, "line-width": 4.5 } },
        { id: SELECTED, type: "line", source: SOURCE, filter: countryFilter([]), paint: { "line-color": token("--map-selected"), "line-width": 2 } },
      ],
    },
  });
  fitWorld(map);
  return map;
}

export const fillLayerId = FILL;

export function paint(map: MapLibreMap, painted: Painted[]) {
  map.setPaintProperty(FILL, "fill-color", fillColour(painted));
}

export function select(map: MapLibreMap, numeric: string | null) {
  for (const layer of ["selected-casing", SELECTED]) map.setFilter(layer, countryFilter(numeric ? [numeric] : []));
}

export function flyToCountry(map: MapLibreMap, bounds: Bounds) {
  map.fitBounds(bounds, { padding: 80, maxZoom: FOCUS_MAX_ZOOM, duration: FLY_MS });
}
