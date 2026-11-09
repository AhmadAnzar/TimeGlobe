import { useEffect, useMemo, useRef, useState } from "react";
import type { LabsFile } from "../data/types";
import { sitePoints, siteLabel, type SitePoint } from "./points";

type GlobeCtor = typeof import("globe.gl").default;

/** A GeoJSON polygon collection, as the processed Natural Earth land file is. */
interface Land {
  features: object[];
}

export const COLORS = {
  background: "#0b1020",
  ocean: "#0e1630",
  land: "#1b2a4a",
  landEdge: "#2b3d66",
  atmosphere: "#4a6fd8",
  point: "#e6ecfb", // neutral: colour is reserved for drift
};

const defaultLandUrl = `${import.meta.env.BASE_URL}geo/land-110m.json`;

function webglAvailable(): boolean {
  const canvas = document.createElement("canvas");
  return Boolean(canvas.getContext("webgl2") ?? canvas.getContext("webgl"));
}

const prefersReducedMotion = () =>
  typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export interface GlobeViewProps {
  labs: LabsFile;
  landUrl?: string;
  /** The globe library is loaded here, on demand, so it is a separate chunk that loads after the page. */
  loadGlobe?: () => Promise<GlobeCtor>;
  webgl?: () => boolean;
  /** For tests: fetch for the land file. */
  fetchLand?: (url: string) => Promise<Land>;
}

type Status = "loading" | "ready" | "unsupported" | "error";

export function GlobeView({
  labs,
  landUrl = defaultLandUrl,
  loadGlobe = () => import("globe.gl").then((module) => module.default),
  webgl = webglAvailable,
  fetchLand = (url) => fetch(url).then((response) => {
    if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
    return response.json() as Promise<Land>;
  }),
}: GlobeViewProps) {
  const container = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<Status>("loading");
  const points = useMemo(() => sitePoints(labs), [labs]);

  useEffect(() => {
    const element = container.current;
    if (!element) return;
    if (!webgl()) {
      setStatus("unsupported");
      return;
    }
    let cancelled = false;
    let dispose = () => {};

    (async () => {
      try {
        const [Globe, land] = await Promise.all([loadGlobe(), fetchLand(landUrl)]);
        if (cancelled) return;

        const world = new Globe(element)
          .backgroundColor(COLORS.background)
          .showAtmosphere(true)
          .atmosphereColor(COLORS.atmosphere)
          .atmosphereAltitude(0.12)
          // Land as flat dark polygons, no raster texture: the points and, later, the drift colours carry the picture.
          .polygonsData(land.features)
          .polygonCapColor(() => COLORS.land)
          .polygonSideColor(() => "rgba(0, 0, 0, 0)")
          .polygonStrokeColor(() => COLORS.landEdge)
          .polygonAltitude(0.004)
          .pointsData(points)
          .pointLat((p) => (p as SitePoint).lat)
          .pointLng((p) => (p as SitePoint).lon)
          .pointRadius((p) => (p as SitePoint).radius)
          .pointAltitude(0.012)
          .pointColor(() => COLORS.point)
          .pointLabel((p) => siteLabel(p as SitePoint));

        (world.globeMaterial() as import("three").MeshPhongMaterial).color.set(COLORS.ocean);
        world.pointOfView({ lat: 25, lng: 15, altitude: 2.5 });
        const controls = world.controls();
        controls.autoRotate = !prefersReducedMotion();
        controls.autoRotateSpeed = 0.35;

        const resize = () => world.width(element.clientWidth).height(element.clientHeight);
        resize();
        const observer = typeof ResizeObserver === "function" ? new ResizeObserver(resize) : null;
        observer?.observe(element);

        dispose = () => {
          observer?.disconnect();
          world._destructor?.();
        };
        setStatus("ready");
      } catch {
        if (!cancelled) setStatus("error");
      }
    })();

    return () => {
      cancelled = true;
      dispose();
    };
  }, [points, landUrl, loadGlobe, webgl, fetchLand]);

  return (
    <section className="globe-panel" aria-label="Globe of the timekeeping laboratories">
      <div
        ref={container}
        className="globe"
        role="img"
        aria-label={`A globe with ${points.length} laboratory sites. The table below lists the same laboratories.`}
      />
      {status === "loading" && <p className="globe-note" role="status">Loading the globe…</p>}
      {status === "unsupported" && (
        <p className="globe-note">This browser cannot show the 3D globe. The table below has the same laboratories.</p>
      )}
      {status === "error" && <p className="globe-note error">The globe could not be loaded. The table below still works.</p>}
    </section>
  );
}
