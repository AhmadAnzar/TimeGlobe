import type { Lab, LabsFile } from "../data/types";

/** One point on the globe: a site, which holds every lab in that city (a shared city is always one point). */
export interface SitePoint {
  id: number;
  lat: number;
  lon: number;
  city: string;
  country: string;
  labs: Lab[];
  /** Clocks not marked stopped, summed over the labs at this site. */
  clocks: number;
  /** Angular radius in degrees, as globe.gl's pointRadius expects. */
  radius: number;
}

const MIN_RADIUS = 0.28; // degrees: a site with no listed clock is still visible
const PER_SQRT_CLOCK = 0.06; // grows with the square root, so USNO's 63 clocks do not hide everything near it

/** Point size grows with the clock count, but gently: area, not radius, tracks the count. */
export function pointRadius(clocks: number): number {
  return MIN_RADIUS + PER_SQRT_CLOCK * Math.sqrt(Math.max(clocks, 0));
}

/** The sites of a snapshot as globe points, in site-id order. Colour is not decided here: points are neutral,
 *  colour is reserved for drift. */
export function sitePoints(labsFile: LabsFile): SitePoint[] {
  const byCode = new Map(labsFile.labs.map((lab) => [lab.code, lab]));
  return labsFile.sites.map((site) => {
    const labs = site.labs.map((code) => byCode.get(code)).filter((lab): lab is Lab => lab !== undefined);
    const clocks = labs.reduce((sum, lab) => sum + lab.clocks, 0);
    return {
      id: site.id,
      lat: site.lat,
      lon: site.lon,
      city: site.city,
      country: site.country,
      labs,
      clocks,
      radius: pointRadius(clocks),
    };
  });
}

const ESCAPES: Record<string, string> = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
export const escapeHtml = (text: string) => text.replace(/[&<>"']/g, (ch) => ESCAPES[ch] ?? ch);

/** The hover tooltip: the city, then every lab at the point with its clock count. Text comes from BIPM's tables,
 *  and is escaped because globe.gl renders the label as HTML. */
export function siteLabel(point: SitePoint): string {
  const rows = point.labs
    .map((lab) => `<div>${escapeHtml(lab.code)} · ${escapeHtml(lab.name)} · ${lab.clocks} ${lab.clocks === 1 ? "clock" : "clocks"}</div>`)
    .join("");
  return `<div class="globe-tip"><strong>${escapeHtml(point.city)}, ${escapeHtml(point.country)}</strong>${rows}</div>`;
}
