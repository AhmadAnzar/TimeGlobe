import { describe, expect, it } from "vitest";
import { fakeFetch, makeSnapshot } from "../test/snapshot";
import { createLoader, SnapshotError, validateCore } from "./loader";

describe("loadCore", () => {
  it("loads exactly the first-load files and the latest year of frames, once each", async () => {
    const { fetchImpl, requested } = fakeFetch(makeSnapshot());
    const loader = createLoader("/data", fetchImpl);
    const core = await loader.loadCore();
    expect(core.labs.labs.map((lab) => lab.code)).toEqual(["AAA", "BBB", "CCC"]);
    expect(core.latestFrame.year).toBe(2026);
    expect([...requested].sort()).toEqual([
      "/data/clusters.json",
      "/data/frames/2026.json",
      "/data/labs.json",
      "/data/meta.json",
      "/data/rapid.json",
    ]);
    await loader.loadCore(); // the second call is served from memory
    expect(requested).toHaveLength(5);
  });

  it("names the file and the status when a request fails, and does not remember the failure", async () => {
    const files = makeSnapshot();
    delete files["rapid.json"];
    const { fetchImpl, requested } = fakeFetch(files);
    const loader = createLoader("/data", fetchImpl);
    await expect(loader.loadCore()).rejects.toThrow("rapid.json: HTTP 404");
    files["rapid.json"] = (makeSnapshot() as Record<string, unknown>)["rapid.json"];
    await expect(loader.loadCore()).resolves.toBeDefined(); // a later attempt asks again
    expect(requested.filter((u) => u.endsWith("rapid.json"))).toHaveLength(2);
  });

  it("wraps a network error in a SnapshotError", async () => {
    const loader = createLoader("/data", () => Promise.reject(new Error("offline")));
    await expect(loader.loadCore()).rejects.toBeInstanceOf(SnapshotError);
  });

  it("loads other frames and lab files on demand under the same base URL", async () => {
    const files = { ...makeSnapshot(), "labs/AAA.json": { code: "AAA", source: "api", mjd: [1], v: [2], u: [null] } };
    const { fetchImpl, requested } = fakeFetch(files);
    const loader = createLoader("/data", fetchImpl);
    expect((await loader.loadFrame(2025)).year).toBe(2025);
    expect((await loader.loadLab("AAA")).code).toBe("AAA");
    expect(requested).toEqual(["/data/frames/2025.json", "/data/labs/AAA.json"]);
  });
});

describe("validateCore", () => {
  const core = async () => createLoader("/data", fakeFetch(makeSnapshot()).fetchImpl).loadCore();

  it("accepts a consistent snapshot", async () => {
    const c = structuredClone(await core());
    expect(() => validateCore(c)).not.toThrow();
  });

  it("rejects a lab count that disagrees with meta.json", async () => {
    const c = structuredClone(await core());
    c.meta.labs = 99;
    expect(() => validateCore(c)).toThrow(/labs.json has 3 labs, meta.json says 99/);
  });

  it("rejects frame columns that differ from labs.json", async () => {
    const c = structuredClone(await core());
    c.latestFrame.labs = ["AAA", "CCC", "BBB"];
    expect(() => validateCore(c)).toThrow(/frame columns differ/);
  });

  it("rejects a rapid file that disagrees on the cutoff or is not provisional", async () => {
    const a = structuredClone(await core());
    a.rapid.after_mjd = 1;
    expect(() => validateCore(a)).toThrow(/cutoff/);
    const b = structuredClone(await core());
    b.rapid.provisional = false;
    expect(() => validateCore(b)).toThrow(/provisional/);
  });

  it("rejects a lab or cluster that points at a missing site", async () => {
    const a = structuredClone(await core());
    a.labs.labs[0]!.site = 9;
    expect(() => validateCore(a)).toThrow(/missing site 9/);
    const b = structuredClone(await core());
    b.clusters.buckets[0]!.clusters[0]!.sites = [0, 7];
    expect(() => validateCore(b)).toThrow(/cluster points at a missing site/);
  });

  it("rejects a snapshot with no years", async () => {
    const files = makeSnapshot();
    (files["meta.json"] as { years: number[] }).years = [];
    const loader = createLoader("/data", fakeFetch(files).fetchImpl);
    await expect(loader.loadCore()).rejects.toThrow(/meta.years is empty/);
  });
});
