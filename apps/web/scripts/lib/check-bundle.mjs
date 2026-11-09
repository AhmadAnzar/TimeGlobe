// The JavaScript budget, enforced after every build (gzip bytes). Separate from the 300 KB first-load DATA budget.
//
// How the numbers were chosen (measured 9 Nov 2026 with a throwaway bundle, then deleted):
//   React + the page, no globe ............... 70 KB   (the first build)
//   globe.gl with three, on its own ........... 559 KB
//   globe.gl + three + react + every approved d3 module ... 636 KB
// So the globe is by far the largest part. The budget leaves room for our own UI and globe code on top
// of the 636 KB, and caps what must load before anything shows (the globe chunk loads after it).
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { gzipSync } from "node:zlib";

export const JS_BUDGET = {
  initialGzip: 100 * 1024, // the scripts index.html loads or preloads: what must arrive before the page is usable
  totalGzip: 750 * 1024, // every JS file in the build
};

const gzipSize = (path) => gzipSync(readFileSync(path), { level: 9 }).length;
const kb = (n) => `${(n / 1024).toFixed(1)} KB`;

/** Scripts the HTML loads up front: module scripts and modulepreload links. Paths are relative to dist/. */
export function initialScripts(html) {
  const found = new Set();
  for (const tag of html.match(/<(?:script|link)\b[^>]*>/g) ?? []) {
    const isScript = /^<script\b/.test(tag) && /type=["']module["']/.test(tag);
    const isPreload = /^<link\b/.test(tag) && /rel=["']modulepreload["']/.test(tag);
    if (!isScript && !isPreload) continue;
    const ref = tag.match(/(?:src|href)=["']([^"']+)["']/)?.[1];
    if (ref?.endsWith(".js")) found.add(ref.replace(/^\//, ""));
  }
  return [...found];
}

/** Returns { ok, lines, initialBytes, totalBytes }. */
export function checkBundle(distDir, budget = JS_BUDGET) {
  const lines = [];
  const assets = join(distDir, "assets");
  if (!existsSync(join(distDir, "index.html")) || !existsSync(assets)) {
    return { ok: false, lines: ["FAIL  dist/ has no index.html or assets: run the build first"], initialBytes: 0, totalBytes: 0 };
  }
  const files = readdirSync(assets).filter((f) => f.endsWith(".js"));
  const sizes = Object.fromEntries(files.map((f) => [`assets/${f}`, gzipSize(join(assets, f))]));
  const initial = initialScripts(readFileSync(join(distDir, "index.html"), "utf8"));
  const initialBytes = initial.reduce((sum, f) => sum + (sizes[f] ?? 0), 0);
  const totalBytes = Object.values(sizes).reduce((a, b) => a + b, 0);

  const ok = initialBytes <= budget.initialGzip && totalBytes <= budget.totalGzip && initial.length > 0;
  lines.push(
    `${initialBytes <= budget.initialGzip && initial.length > 0 ? "PASS" : "FAIL"}  initial JS ${kb(initialBytes)} gzip, budget ${kb(budget.initialGzip)}`,
    `${totalBytes <= budget.totalGzip ? "PASS" : "FAIL"}  total JS ${kb(totalBytes)} gzip, budget ${kb(budget.totalGzip)}`,
  );
  for (const [file, size] of Object.entries(sizes).sort((a, b) => b[1] - a[1])) {
    lines.push(`INFO  ${file}  ${kb(size)} gzip${initial.includes(file) ? "  (initial)" : ""}`);
  }
  return { ok, lines, initialBytes, totalBytes };
}
