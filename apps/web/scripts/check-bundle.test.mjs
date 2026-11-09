// @vitest-environment node
import { randomBytes } from "node:crypto";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { JS_BUDGET, checkBundle, initialScripts } from "./lib/check-bundle.mjs";

const dirs = [];
afterEach(() => {
  while (dirs.length) rmSync(dirs.pop(), { recursive: true, force: true });
});

const incompressible = (bytes) => randomBytes(bytes); // random bytes do not shrink under gzip

function dist(files, html) {
  const dir = mkdtempSync(join(tmpdir(), "dist-"));
  dirs.push(dir);
  mkdirSync(join(dir, "assets"));
  writeFileSync(join(dir, "index.html"), html);
  for (const [name, body] of Object.entries(files)) writeFileSync(join(dir, "assets", name), body);
  return dir;
}

const page = (...tags) => `<!doctype html><html><head>${tags.join("")}</head><body></body></html>`;

describe("initialScripts", () => {
  it("finds the module script and modulepreload links, and nothing else", () => {
    const html = page(
      '<script type="module" crossorigin src="/assets/index-a.js"></script>',
      '<link rel="modulepreload" crossorigin href="/assets/vendor-b.js">',
      '<link rel="stylesheet" href="/assets/index.css">',
      '<script src="/assets/legacy.js"></script>',
    );
    expect(initialScripts(html)).toEqual(["assets/index-a.js", "assets/vendor-b.js"]);
  });
});

describe("checkBundle", () => {
  const small = '<script type="module" src="/assets/index.js"></script>';

  it("passes a build inside both budgets and reports each chunk", () => {
    const { ok, lines } = checkBundle(dist({ "index.js": incompressible(30_000) }, page(small)));
    expect(ok, lines.join("\n")).toBe(true);
    expect(lines.some((l) => l.includes("assets/index.js") && l.includes("(initial)"))).toBe(true);
  });

  it("fails when the initial JS is over its budget even if the total is fine", () => {
    const { ok, lines } = checkBundle(dist({ "index.js": incompressible(JS_BUDGET.initialGzip + 20_000) }, page(small)));
    expect(ok).toBe(false);
    expect(lines.find((l) => l.startsWith("FAIL  initial JS"))).toBeDefined();
  });

  it("does not count a lazily loaded chunk as initial, but does count it in the total", () => {
    const files = { "index.js": incompressible(20_000), "globe.js": incompressible(400_000) };
    const { ok, initialBytes, totalBytes } = checkBundle(dist(files, page(small)));
    expect(ok).toBe(true); // 400 KB lazy chunk: allowed, it is not initial
    expect(initialBytes).toBeLessThan(30_000);
    expect(totalBytes).toBeGreaterThan(400_000);
  });

  it("fails when the total is over budget", () => {
    const files = { "index.js": incompressible(20_000), "globe.js": incompressible(JS_BUDGET.totalGzip + 10_000) };
    const { ok, lines } = checkBundle(dist(files, page(small)));
    expect(ok).toBe(false);
    expect(lines.find((l) => l.startsWith("FAIL  total JS"))).toBeDefined();
  });

  it("fails when the page loads no script at all, or there is no build", () => {
    expect(checkBundle(dist({ "index.js": incompressible(1000) }, page())).ok).toBe(false);
    expect(checkBundle(join(tmpdir(), "no-such-dist")).ok).toBe(false);
  });
});
