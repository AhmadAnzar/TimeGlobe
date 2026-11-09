// @vitest-environment node
import { existsSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { roundGeoJson, roundRing } from "./lib/round-geojson.mjs";

const square = (x0, y0, size) => [
  [x0, y0],
  [x0 + size, y0],
  [x0 + size, y0 + size],
  [x0, y0 + size],
  [x0, y0],
];
const polygon = (...rings) => ({
  type: "Feature",
  properties: { featurecla: "Land" },
  bbox: [0, 0, 1, 1],
  geometry: { type: "Polygon", coordinates: rings },
});
const collection = (...features) => ({ type: "FeatureCollection", name: "x", crs: {}, features });

describe("roundRing", () => {
  it("rounds to the requested decimals", () => {
    const ring = roundRing(square(10.123456, 20.987654, 5.555555), 2);
    expect(ring[0]).toEqual([10.12, 20.99]);
    expect(ring[2]).toEqual([15.68, 26.54]);
  });

  it("removes consecutive duplicates that rounding creates and keeps the ring closed", () => {
    const ring = roundRing(
      [[0, 0], [0.001, 0.002], [1, 0], [1, 1], [0, 1], [0.0004, 0.0004]],
      2,
    );
    expect(ring).toEqual([[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]);
  });

  it("never writes negative zero", () => {
    const ring = roundRing([[-0.001, 5], [1, 5], [1, 6], [-0.004, 5]], 2);
    expect(Object.is(ring[0][0], -0)).toBe(false);
    expect(ring[0]).toEqual([0, 5]);
  });

  it("returns null for a ring that rounds away to fewer than 4 positions", () => {
    expect(roundRing(square(1, 1, 0.001), 2)).toBeNull();
  });
});

describe("roundGeoJson", () => {
  it("keeps geometry only and drops properties, bbox, crs and name", () => {
    const { geojson } = roundGeoJson(collection(polygon(square(0, 0, 1))), 2);
    expect(Object.keys(geojson)).toEqual(["type", "features"]);
    expect(geojson.features[0]).toEqual({
      type: "Feature",
      properties: {},
      geometry: { type: "Polygon", coordinates: [square(0, 0, 1)] },
    });
  });

  it("drops a speck whose outer ring vanishes and a hole that vanishes, and counts them", () => {
    const { geojson, stats } = roundGeoJson(
      collection(
        polygon(square(0, 0, 10), square(2, 2, 0.001)), // big land, a hole too small to survive
        polygon(square(50, 50, 0.001)), // a speck
      ),
      2,
    );
    expect(geojson.features).toHaveLength(1);
    expect(geojson.features[0].geometry.coordinates).toHaveLength(1); // the hole is gone
    expect(stats).toEqual({ featuresIn: 2, featuresOut: 1, ringsDropped: 1, featuresDropped: 1 });
  });

  it("refuses a geometry type it was not written for rather than guessing", () => {
    const multi = { type: "Feature", properties: {}, geometry: { type: "MultiPolygon", coordinates: [] } };
    expect(() => roundGeoJson(collection(multi), 2)).toThrow(/MultiPolygon/);
  });
});

// The committed processed file: written by scripts/prepare-land.mjs, checked here so it cannot rot.
const LAND = new URL("../public/geo/land-110m.json", import.meta.url);

describe.skipIf(!existsSync(LAND))("public/geo/land-110m.json", () => {
  const text = readFileSync(LAND, "utf8");
  const land = JSON.parse(text);

  it("is a FeatureCollection of polygons with no leftover properties", () => {
    expect(land.type).toBe("FeatureCollection");
    expect(land.features.length).toBeGreaterThan(100);
    expect(land.features.every((f) => f.geometry.type === "Polygon" && Object.keys(f.properties).length === 0)).toBe(true);
  });

  it("has no coordinate with more than 2 decimals", () => {
    expect(/\d\.\d{3,}/.test(text)).toBe(false);
  });

  it("has closed rings of at least 4 positions, inside the world", () => {
    for (const feature of land.features) {
      for (const ring of feature.geometry.coordinates) {
        expect(ring.length).toBeGreaterThanOrEqual(4);
        expect(ring[0]).toEqual(ring[ring.length - 1]);
        for (const [lon, lat] of ring) {
          expect(lon).toBeGreaterThanOrEqual(-180);
          expect(lon).toBeLessThanOrEqual(180);
          expect(lat).toBeGreaterThanOrEqual(-90);
          expect(lat).toBeLessThanOrEqual(90);
        }
      }
    }
  });
});
