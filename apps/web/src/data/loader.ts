import type { ClustersFile, Frame, LabDetail, LabsFile, Meta, RapidFile } from "./types";

export class SnapshotError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SnapshotError";
  }
}

/** What the page needs for its first frame: small by design (see the 300 KB first-load budget). */
export interface CoreData {
  meta: Meta;
  labs: LabsFile;
  rapid: RapidFile;
  clusters: ClustersFile;
  latestFrame: Frame;
}

type FetchLike = (url: string) => Promise<Response>;

const sameList = (a: readonly string[], b: readonly string[]) =>
  a.length === b.length && a.every((code, i) => code === b[i]);

/** Cross-file consistency: the files are published together, so a mismatch means a broken or half-copied snapshot. */
export function validateCore(core: CoreData): void {
  const { meta, labs, rapid, clusters, latestFrame } = core;
  const codes = labs.labs.map((lab) => lab.code);
  const fail = (what: string): never => {
    throw new SnapshotError(`snapshot is inconsistent: ${what}`);
  };

  if (!Array.isArray(meta.years) || meta.years.length === 0) fail("meta.years is empty");
  if (labs.labs.length !== meta.labs) fail(`labs.json has ${labs.labs.length} labs, meta.json says ${meta.labs}`);
  const withData = labs.labs.filter((lab) => lab.has_data).length;
  if (withData !== meta.labs_with_data) fail(`${withData} labs have data, meta.json says ${meta.labs_with_data}`);
  for (const lab of labs.labs) {
    if (!labs.sites[lab.site]) fail(`lab ${lab.code} points at missing site ${lab.site}`);
  }

  if (latestFrame.year !== meta.years[meta.years.length - 1]) fail("the loaded frame is not the latest year");
  if (!sameList(latestFrame.labs, codes)) fail("frame columns differ from labs.json");
  if (latestFrame.v.some((row) => row.length !== codes.length)) fail("a frame row has the wrong width");

  if (!sameList(rapid.labs, codes)) fail("rapid.json columns differ from labs.json");
  if (rapid.after_mjd !== meta.rapid.after_mjd) fail("rapid.json and meta.json disagree on the cutoff date");
  if (!rapid.provisional) fail("rapid.json is not marked provisional");

  if (clusters.buckets.length === 0) fail("clusters.json has no buckets");
  for (const bucket of clusters.buckets) {
    for (const cluster of bucket.clusters) {
      if (cluster.sites.some((id) => !labs.sites[id])) fail("a cluster points at a missing site");
    }
  }
}

/**
 * Loads snapshot files over HTTP from baseUrl (the copy made at build time under /data) and keeps what it has loaded.
 * `fetchImpl` is injectable so tests need no network.
 */
export function createLoader(baseUrl = "/data", fetchImpl: FetchLike = (url) => fetch(url)) {
  const cache = new Map<string, Promise<unknown>>();

  function getJson<T>(path: string): Promise<T> {
    const cached = cache.get(path);
    if (cached) return cached as Promise<T>;
    const request = fetchImpl(`${baseUrl}/${path}`)
      .then((response) => {
        if (!response.ok) throw new SnapshotError(`${path}: HTTP ${response.status}`);
        return response.json() as Promise<T>;
      })
      .catch((error: unknown) => {
        cache.delete(path); // a failed request is not remembered
        throw error instanceof SnapshotError ? error : new SnapshotError(`${path}: ${String(error)}`);
      });
    cache.set(path, request);
    return request;
  }

  return {
    async loadCore(): Promise<CoreData> {
      const meta = await getJson<Meta>("meta.json");
      const latest = Array.isArray(meta.years) ? meta.years[meta.years.length - 1] : undefined;
      if (latest === undefined) throw new SnapshotError("snapshot is inconsistent: meta.years is empty");
      const [labs, rapid, clusters, latestFrame] = await Promise.all([
        getJson<LabsFile>("labs.json"),
        getJson<RapidFile>("rapid.json"),
        getJson<ClustersFile>("clusters.json"),
        getJson<Frame>(`frames/${latest}.json`),
      ]);
      const core: CoreData = { meta, labs, rapid, clusters, latestFrame };
      validateCore(core);
      return core;
    },
    loadFrame: (year: number) => getJson<Frame>(`frames/${year}.json`),
    loadLab: (code: string) => getJson<LabDetail>(`labs/${code}.json`),
  };
}

export type Loader = ReturnType<typeof createLoader>;
