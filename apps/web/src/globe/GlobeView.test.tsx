import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { LabsFile } from "../data/types";
import { makeSnapshot } from "../test/snapshot";
import { COLORS, GlobeView, type GlobeViewProps } from "./GlobeView";
import type { SitePoint } from "./points";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

/** A stand-in for globe.gl: every chained call is recorded, nothing is drawn. */
function fakeGlobe() {
  const calls: Record<string, unknown[][]> = {};
  const controls = { autoRotate: undefined as boolean | undefined, autoRotateSpeed: 0 };
  const material = { color: { set: (c: string) => (calls["materialColor"] = [[c]]) } };
  let destroyed = 0;
  let constructedWith: HTMLElement | undefined;
  const world: Record<string, unknown> = new Proxy({}, {
    get(_target, name: string) {
      if (name === "globeMaterial") return () => material;
      if (name === "controls") return () => controls;
      if (name === "_destructor") return () => destroyed++;
      return (...args: unknown[]) => {
        (calls[name] ??= []).push(args);
        return world;
      };
    },
  });
  class FakeCtor {
    constructor(element: HTMLElement) {
      constructedWith = element;
      return world as unknown as FakeCtor;
    }
  }
  return { Ctor: FakeCtor as unknown as Awaited<ReturnType<NonNullable<GlobeViewProps["loadGlobe"]>>>, calls, controls, material, get destroyed() { return destroyed; }, get element() { return constructedWith; } };
}

const land = { features: [{ type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [] } }] };
const labs = () => makeSnapshot()["labs.json"] as LabsFile;

let container: HTMLElement;
let root: Root;
beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function mount(props: Partial<GlobeViewProps>, labsFile = labs()) {
  await act(async () => {
    root.render(<GlobeView labs={labsFile} webgl={() => true} fetchLand={async () => land} {...props} />);
  });
}

describe("GlobeView", () => {
  it("draws the land as flat polygons and one neutral point per site", async () => {
    const fake = fakeGlobe();
    await mount({ loadGlobe: async () => fake.Ctor });
    expect(fake.calls["polygonsData"]![0]![0]).toBe(land.features);
    const points = fake.calls["pointsData"]![0]![0] as SitePoint[];
    expect(points.map((p) => p.city)).toEqual(["Alphaville", "Betaburg"]); // three labs, two sites
    const colour = fake.calls["pointColor"]![0]![0] as () => string;
    expect(colour()).toBe(COLORS.point); // neutral for every point
    expect(fake.calls["polygonCapColor"]![0]![0]).toBeTypeOf("function");
    expect(fake.calls["globeImageUrl"]).toBeUndefined(); // no raster texture
  });

  it("sizes points from the sites, positions them by lat/lon, and labels them with the tooltip", async () => {
    const fake = fakeGlobe();
    await mount({ loadGlobe: async () => fake.Ctor });
    const [alpha] = fake.calls["pointsData"]![0]![0] as SitePoint[];
    expect((fake.calls["pointLat"]![0]![0] as (p: SitePoint) => number)(alpha!)).toBe(10);
    expect((fake.calls["pointLng"]![0]![0] as (p: SitePoint) => number)(alpha!)).toBe(20);
    expect((fake.calls["pointRadius"]![0]![0] as (p: SitePoint) => number)(alpha!)).toBe(alpha!.radius);
    expect((fake.calls["pointLabel"]![0]![0] as (p: SitePoint) => string)(alpha!)).toContain("Alpha Institute");
  });

  it("mounts the globe in its own element and sets the ocean colour and the starting view", async () => {
    const fake = fakeGlobe();
    await mount({ loadGlobe: async () => fake.Ctor });
    expect(fake.element).toBe(container.querySelector(".globe"));
    expect(fake.calls["materialColor"]![0]![0]).toBe(COLORS.ocean);
    expect(fake.calls["pointOfView"]![0]![0]).toMatchObject({ altitude: 2.5 });
  });

  it("does not auto-rotate when the user prefers reduced motion", async () => {
    const original = window.matchMedia;
    window.matchMedia = ((query: string) => ({ matches: query.includes("reduce") })) as typeof window.matchMedia;
    const fake = fakeGlobe();
    await mount({ loadGlobe: async () => fake.Ctor });
    expect(fake.controls.autoRotate).toBe(false);
    window.matchMedia = original;
  });

  it("auto-rotates by default", async () => {
    const fake = fakeGlobe();
    await mount({ loadGlobe: async () => fake.Ctor });
    expect(fake.controls.autoRotate).toBe(true);
  });

  it("is described to assistive technology and points to the table", async () => {
    await mount({ loadGlobe: async () => fakeGlobe().Ctor });
    const label = container.querySelector(".globe")?.getAttribute("aria-label");
    expect(label).toContain("2 laboratory sites");
    expect(label).toContain("table");
  });

  it("releases the globe when it is removed", async () => {
    const fake = fakeGlobe();
    await mount({ loadGlobe: async () => fake.Ctor });
    await act(async () => root.render(<div />));
    expect(fake.destroyed).toBe(1);
  });

  it("says so, and loads nothing, when the browser has no WebGL", async () => {
    let loaded = false;
    await mount({ webgl: () => false, loadGlobe: async () => { loaded = true; return fakeGlobe().Ctor; } });
    expect(container.textContent).toContain("cannot show the 3D globe");
    expect(loaded).toBe(false);
  });

  it("falls back to a message when the globe or the land cannot be loaded", async () => {
    await mount({ loadGlobe: async () => { throw new Error("chunk failed"); } });
    expect(container.textContent).toContain("could not be loaded");
    await act(async () => root.render(<div />));
    await mount({ loadGlobe: async () => fakeGlobe().Ctor, fetchLand: async () => { throw new Error("404"); } });
    expect(container.textContent).toContain("could not be loaded");
  });
});
