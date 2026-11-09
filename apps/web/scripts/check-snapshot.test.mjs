// @vitest-environment node
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { randomBytes } from "node:crypto";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { FIRST_LOAD_BUDGET, checkSnapshot } from "./lib/check-snapshot.mjs";

const dirs = [];
afterEach(() => {
  while (dirs.length) rmSync(dirs.pop(), { recursive: true, force: true });
});

/** A minimal valid snapshot on disk; `change` may edit the file map before it is written. */
function snapshot(change = () => {}) {
  const dir = mkdtempSync(join(tmpdir(), "snapshot-"));
  dirs.push(dir);
  const files = {
    "meta.json": {
      attribution: "Time data: BIPM. Not affiliated with or endorsed by BIPM.",
      circular_t_latest: 465, generated_at: "2026-11-09", labs: 2, labs_with_data: 1, values: 3,
      years: [2025, 2026], rapid: { after_mjd: 61309, labs: 0, provisional: true },
    },
    "labs.json": { labs: [{ code: "AAA" }, { code: "BBB" }], sites: [] },
    "rapid.json": { provisional: true, after_mjd: 61309, labs: ["AAA", "BBB"], mjd: [], v: [] },
    "clusters.json": { cap_km: 500, buckets: [] },
    "gnss.json": {},
    "frames/2025.json": { year: 2025 },
    "frames/2026.json": { year: 2026 },
    "labs/AAA.json": { code: "AAA" },
  };
  change(files);
  for (const [name, body] of Object.entries(files)) {
    const path = join(dir, name);
    mkdirSync(join(path, ".."), { recursive: true });
    writeFileSync(path, typeof body === "string" ? body : JSON.stringify(body));
  }
  return dir;
}

describe("checkSnapshot", () => {
  it("passes a complete, consistent snapshot", () => {
    const { ok, lines } = checkSnapshot(snapshot());
    expect(ok, lines.join("\n")).toBe(true);
    expect(lines.some((l) => l.startsWith("FAIL"))).toBe(false);
  });

  it("fails when a required file is missing", () => {
    const { ok, lines } = checkSnapshot(snapshot((f) => delete f["rapid.json"]));
    expect(ok).toBe(false);
    expect(lines).toContain("FAIL  rapid.json exists");
  });

  it("fails when the frame files do not match meta.years", () => {
    const { ok, lines } = checkSnapshot(snapshot((f) => delete f["frames/2025.json"]));
    expect(ok).toBe(false);
    expect(lines.find((l) => l.startsWith("FAIL  frame files"))).toBeDefined();
  });

  it("fails when the number of lab files differs from the labs with data", () => {
    const { ok } = checkSnapshot(snapshot((f) => (f["labs/BBB.json"] = { code: "BBB" })));
    expect(ok).toBe(false);
  });

  it("fails when the attribution lost its 'not affiliated' statement", () => {
    const { ok } = checkSnapshot(snapshot((f) => (f["meta.json"].attribution = "Time data: BIPM.")));
    expect(ok).toBe(false);
  });

  it("fails when the first load exceeds the 300 KB budget", () => {
    // random bytes do not compress, so this really is over the gzip budget
    const big = randomBytes(FIRST_LOAD_BUDGET + 50_000).toString("base64");
    const { ok, lines, firstLoadBytes } = checkSnapshot(snapshot((f) => (f["clusters.json"] = { filler: big })));
    expect(ok).toBe(false);
    expect(firstLoadBytes).toBeGreaterThan(FIRST_LOAD_BUDGET);
    expect(lines.find((l) => l.startsWith("FAIL  first-load data under 300 KB"))).toBeDefined();
  });
});
