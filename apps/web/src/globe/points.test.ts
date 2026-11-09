import { describe, expect, it } from "vitest";
import { makeSnapshot } from "../test/snapshot";
import type { LabsFile } from "../data/types";
import { escapeHtml, pointRadius, siteLabel, sitePoints } from "./points";

const labsFile = () => makeSnapshot()["labs.json"] as LabsFile;

describe("pointRadius", () => {
  it("is never below the minimum and grows with the clock count", () => {
    expect(pointRadius(0)).toBeCloseTo(0.28);
    expect(pointRadius(0)).toBeLessThan(pointRadius(5));
    expect(pointRadius(5)).toBeLessThan(pointRadius(63));
  });

  it("grows gently: 63 clocks is under three times the radius of 0", () => {
    expect(pointRadius(63) / pointRadius(0)).toBeLessThan(3);
  });

  it("ignores a negative count", () => {
    expect(pointRadius(-4)).toBe(pointRadius(0));
  });
});

describe("sitePoints", () => {
  it("makes one point per site, so labs in the same city are one point", () => {
    const points = sitePoints(labsFile());
    expect(points).toHaveLength(2); // three labs, but BBB and CCC share a city
    expect(points.map((p) => p.labs.map((l) => l.code))).toEqual([["AAA"], ["BBB", "CCC"]]);
  });

  it("sums the clocks of every lab at a site and sizes the point by that sum", () => {
    const [alpha, beta] = sitePoints(labsFile());
    expect(alpha!.clocks).toBe(5);
    expect(beta!.clocks).toBe(2); // BBB has 2, the former CCC has 0
    expect(alpha!.radius).toBeCloseTo(pointRadius(5));
    expect(alpha!.radius).toBeGreaterThan(beta!.radius);
  });

  it("keeps the site's position and names", () => {
    const [alpha] = sitePoints(labsFile());
    expect(alpha).toMatchObject({ id: 0, lat: 10, lon: 20, city: "Alphaville", country: "Land of A" });
  });

  it("gives points no colour: colour is reserved for drift", () => {
    expect(Object.keys(sitePoints(labsFile())[0]!)).not.toContain("color");
  });
});

describe("siteLabel", () => {
  it("lists every lab at a shared point with its clock count", () => {
    const label = siteLabel(sitePoints(labsFile())[1]!);
    expect(label).toContain("Betaburg, Land of B");
    expect(label).toContain("BBB · Beta Observatory · 2 clocks");
    expect(label).toContain("CCC · Gamma Standards · 0 clocks");
  });

  it("says '1 clock' in the singular", () => {
    const file = labsFile();
    file.labs[0]!.clocks = 1;
    expect(siteLabel(sitePoints(file)[0]!)).toContain("1 clock<");
  });

  it("escapes text, because globe.gl renders the label as HTML", () => {
    const file = labsFile();
    file.labs[0]!.name = '<img src=x onerror="alert(1)">';
    file.sites[0]!.city = "A&B";
    const label = siteLabel(sitePoints(file)[0]!);
    expect(label).not.toContain("<img");
    expect(label).toContain("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;");
    expect(label).toContain("A&amp;B");
  });
});

describe("escapeHtml", () => {
  it("escapes the five characters that matter", () => {
    expect(escapeHtml(`<a href="x">'&'</a>`)).toBe("&lt;a href=&quot;x&quot;&gt;&#39;&amp;&#39;&lt;/a&gt;");
  });
});
