// A tiny synthetic snapshot for tests, in the shape the pipeline publishes. Three labs: AAA alone, BBB and CCC share a city.
import type { ClustersFile, Frame, LabsFile, Meta, RapidFile } from "../data/types";

export function makeSnapshot(): Record<string, unknown> {
  const codes = ["AAA", "BBB", "CCC"];
  const labs: LabsFile = {
    labs: [
      { code: "AAA", name: "Alpha Institute", city: "Alphaville", country: "Land of A", iso2: "AA", lat: 10, lon: 20, year_start: 1990, year_stop: null, status: "current", clocks: 5, site: 0, has_data: true },
      { code: "BBB", name: "Beta Observatory", city: "Betaburg", country: "Land of B", iso2: "BB", lat: 30, lon: 40, year_start: 2001, year_stop: null, status: "current", clocks: 2, site: 1, has_data: true },
      { code: "CCC", name: "Gamma Standards", city: "Betaburg", country: "Land of B", iso2: "BB", lat: 30, lon: 40, year_start: 2010, year_stop: 2020, status: "former", clocks: 0, site: 1, has_data: false },
    ],
    sites: [
      { id: 0, lat: 10, lon: 20, city: "Alphaville", country: "Land of A", labs: ["AAA"] },
      { id: 1, lat: 30, lon: 40, city: "Betaburg", country: "Land of B", labs: ["BBB", "CCC"] },
    ],
  };
  const meta: Meta = {
    attribution: "Time data: BIPM, CC BY 4.0. Not affiliated with or endorsed by BIPM.",
    circular_t_latest: 465,
    generated_at: "2026-11-09",
    mjd_first: 50814,
    mjd_last: 61309,
    labs: 3,
    labs_with_data: 2,
    values: 7,
    years: [2025, 2026],
    unit: "values are integer tenths of a nanosecond; null means no data",
    flags: {},
    clocks: { definition: "clocks not marked stopped on the Time Database clock list", total: 9, in_labs: 7, unmapped: { F: 2 } },
    rapid: { provisional: true, after_mjd: 61309, labs: 1 },
  };
  const frame = (year: number): Frame => ({ year, labs: codes, mjd: [61304, 61309], v: [[1, 2, null], [3, null, null]] });
  const rapid: RapidFile = { provisional: true, after_mjd: 61309, labs: codes, mjd: [61310], v: [[5, null, null]] };
  const clusters: ClustersFile = {
    unit: "altitude in globe radii",
    cap_km: 500,
    buckets: [{ altitude: 2.5, radius_km: 500, min_altitude: 1.95, max_altitude: null, clusters: [{ lat: 20, lon: 30, labs: ["AAA", "BBB", "CCC"], sites: [0, 1] }] }],
  };
  return {
    "meta.json": meta,
    "labs.json": labs,
    "rapid.json": rapid,
    "clusters.json": clusters,
    "frames/2025.json": frame(2025),
    "frames/2026.json": frame(2026),
  };
}

/** A fetch that serves the given files as JSON and answers 404 for anything else. */
export function fakeFetch(files: Record<string, unknown>) {
  const requested: string[] = [];
  const fetchImpl = (url: string): Promise<Response> => {
    requested.push(url);
    const path = url.replace(/^\/data\//, "");
    const body = files[path];
    return Promise.resolve(
      body === undefined ? new Response("not found", { status: 404 }) : new Response(JSON.stringify(body), { status: 200 }),
    );
  };
  return { fetchImpl, requested };
}
