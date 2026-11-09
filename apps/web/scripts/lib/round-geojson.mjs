// Rounds the coordinates of a GeoJSON FeatureCollection of polygons and strips what the globe does not use.
// Pure functions, no I/O, so they can be tested. Used by scripts/prepare-land.mjs.

const round = (value, decimals) => {
  const factor = 10 ** decimals;
  const rounded = Math.round(value * factor) / factor;
  return rounded === 0 ? 0 : rounded; // never write -0
};

/** Round a ring, drop consecutive duplicate points the rounding created, and keep it closed.
 *  Returns null when fewer than 4 positions are left (a ring needs 3 distinct points + the closing one). */
export function roundRing(ring, decimals) {
  const points = [];
  for (const [x, y] of ring) {
    const point = [round(x, decimals), round(y, decimals)];
    const last = points[points.length - 1];
    if (!last || last[0] !== point[0] || last[1] !== point[1]) points.push(point);
  }
  const first = points[0];
  const last = points[points.length - 1];
  if (first && (first[0] !== last[0] || first[1] !== last[1])) points.push([...first]);
  return points.length >= 4 ? points : null;
}

/** Returns { geojson, stats }. Only Polygon features are expected (ne_110m_land has nothing else).
 *  properties, bbox, crs and name are dropped: the globe draws geometry only. */
export function roundGeoJson(input, decimals = 2) {
  const stats = { featuresIn: input.features.length, featuresOut: 0, ringsDropped: 0, featuresDropped: 0 };
  const features = [];
  for (const feature of input.features) {
    if (feature.geometry.type !== "Polygon") {
      throw new Error(`unexpected geometry type ${feature.geometry.type}`);
    }
    const [outer, ...holes] = feature.geometry.coordinates;
    const outerRounded = roundRing(outer, decimals);
    if (!outerRounded) {
      stats.featuresDropped += 1; // a speck that rounds away to nothing
      continue;
    }
    const keptHoles = [];
    for (const hole of holes) {
      const rounded = roundRing(hole, decimals);
      if (rounded) keptHoles.push(rounded);
      else stats.ringsDropped += 1;
    }
    features.push({
      type: "Feature",
      properties: {},
      geometry: { type: "Polygon", coordinates: [outerRounded, ...keptHoles] },
    });
  }
  stats.featuresOut = features.length;
  return { geojson: { type: "FeatureCollection", features }, stats };
}
