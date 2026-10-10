// Country polygons shipped with the app (world-atlas 50m), joined to trackers by
// ISO numeric code. Ported from the conflict map's frontend/src/map/countries.ts.
import type { FeatureCollection, MultiPolygon, Polygon, Position } from "geojson";
import { feature } from "topojson-client";
import countriesTopology from "world-atlas/countries-50m.json";

type CountryProperties = { name: string; numeric?: string };
type CountryShapes = FeatureCollection<Polygon | MultiPolygon, CountryProperties>;
export type Bounds = [west: number, south: number, east: number, north: number];

// world-atlas keeps a shape that crosses the antimeridian (Russia, one island of
// Fiji) as one ring whose longitudes jump between +180 and -180. Shifting the
// longitudes after a jump keeps the ring continuous; MapLibre wraps the rest.
function continuousLongitudes(ring: Position[]): Position[] {
  let shift = 0;
  const continuous = ring.map(([longitude, latitude], index) => {
    const jump = index === 0 ? 0 : longitude - ring[index - 1][0];
    if (jump > 180) shift -= 360;
    else if (jump < -180) shift += 360;
    return [longitude + shift, latitude];
  });
  // A ring that ends shifted circles a pole (Antarctica) and is left alone.
  return shift === 0 ? continuous : ring;
}

let cached: CountryShapes | null = null;

export function countryShapes(): CountryShapes {
  if (cached) return cached;
  const topology = countriesTopology as unknown as Parameters<typeof feature>[0];
  const shapes = feature(topology, topology.objects.countries) as CountryShapes;
  for (const shape of shapes.features) {
    if (shape.id !== undefined) shape.properties.numeric = shape.id.toString();
    if (shape.geometry.type === "Polygon") {
      shape.geometry.coordinates = shape.geometry.coordinates.map(continuousLongitudes);
    } else {
      shape.geometry.coordinates = shape.geometry.coordinates.map((polygon) => polygon.map(continuousLongitudes));
    }
  }
  cached = shapes;
  return shapes;
}

// The bounds of the country's largest ring, not of its whole shape: France's
// multipolygon includes French Guiana, so the whole shape spans the Atlantic.
// null when the 50m file has no shape for the country.
export function boundsOfCountry(numeric: string): Bounds | null {
  const rings = countryShapes()
    .features.filter((shape) => shape.properties.numeric === numeric)
    .flatMap((shape) => (shape.geometry.type === "Polygon" ? [shape.geometry.coordinates] : shape.geometry.coordinates))
    .map((polygon) => polygon[0]);
  if (!rings.length) return null;
  const largest = rings.reduce((best, ring) => (ring.length > best.length ? ring : best));
  let west = Infinity, south = Infinity, east = -Infinity, north = -Infinity;
  for (const [longitude, latitude] of largest) {
    west = Math.min(west, longitude);
    south = Math.min(south, latitude);
    east = Math.max(east, longitude);
    north = Math.max(north, latitude);
  }
  return [west, south, east, north];
}
