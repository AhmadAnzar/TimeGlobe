// The web build's own guard on the copied snapshot: it is complete, internally consistent, and the first load
// stays inside the data budget. (The pipeline has a fuller set of checks; this is what the build must not ship without.)
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { gzipSync } from "node:zlib";

export const FIRST_LOAD_BUDGET = 300 * 1024; // gzip bytes of data for the first frame (SCOPE: under 300 KB)

const gzipSize = (path) => gzipSync(readFileSync(path), { level: 9 }).length;
const REQUIRED = ["meta.json", "labs.json", "rapid.json", "clusters.json", "gnss.json"];

/** Returns { ok, lines, firstLoadBytes }. Never throws on a bad snapshot: it reports FAIL lines. */
export function checkSnapshot(dir) {
  const lines = [];
  let ok = true;
  const check = (name, passed, detail = "") => {
    ok = ok && passed;
    lines.push(`${passed ? "PASS" : "FAIL"}  ${name}${!passed && detail ? `: ${detail}` : ""}`);
  };

  for (const name of REQUIRED) check(`${name} exists`, existsSync(join(dir, name)));
  if (!ok) return { ok, lines, firstLoadBytes: 0 };

  const read = (name) => JSON.parse(readFileSync(join(dir, name), "utf8"));
  const meta = read("meta.json");
  const labs = read("labs.json");
  const rapid = read("rapid.json");

  const frameYears = existsSync(join(dir, "frames"))
    ? readdirSync(join(dir, "frames")).map((f) => Number(f.replace(".json", ""))).sort((a, b) => a - b)
    : [];
  const labFiles = existsSync(join(dir, "labs")) ? readdirSync(join(dir, "labs")).length : 0;

  check("frame files match meta.years", JSON.stringify(frameYears) === JSON.stringify(meta.years), `${frameYears.length} files vs ${meta.years.length} years`);
  check("labs.json has meta.labs labs", labs.labs.length === meta.labs, `${labs.labs.length} vs ${meta.labs}`);
  check("one lab file per lab with data", labFiles === meta.labs_with_data, `${labFiles} vs ${meta.labs_with_data}`);
  check("rapid.json and meta.json agree on the cutoff", rapid.after_mjd === meta.rapid.after_mjd);
  check("the attribution says the data is not an official BIPM product", /Not affiliated with or endorsed by BIPM/.test(meta.attribution));

  const latest = meta.years[meta.years.length - 1];
  const firstLoad = ["meta.json", "labs.json", "rapid.json", "clusters.json", `frames/${latest}.json`].map((f) => join(dir, f));
  const missing = firstLoad.filter((f) => !existsSync(f));
  check("every first-load file exists", missing.length === 0, missing.join(", "));
  const firstLoadBytes = missing.length === 0 ? firstLoad.reduce((sum, f) => sum + gzipSize(f), 0) : 0;
  check(
    `first-load data under 300 KB (${(firstLoadBytes / 1024).toFixed(1)} KB gzip)`,
    missing.length === 0 && firstLoadBytes < FIRST_LOAD_BUDGET,
  );
  lines.push(`INFO  Circular T ${meta.circular_t_latest}, data last changed ${meta.generated_at}, ${meta.labs_with_data} labs with data, ${meta.values} values`);
  return { ok, lines, firstLoadBytes };
}
