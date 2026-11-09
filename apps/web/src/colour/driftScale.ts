import { interpolatePuOr } from "d3-scale-chromatic";
import { scaleDivergingSymlog, type ScaleDiverging } from "d3-scale";

// The approved drift colour scale (docs/phase1-findings.md): symmetric log, linear within ±5 ns, saturated at
// ±10,000 ns, purple-orange PuOr. The Python spike (timeglobe_pipeline.spike_coverage) is the reference;
// driftScale.test.ts checks this module against golden values generated from it.
export const LINTHRESH_NS = 5;
export const CLIP_NS = 10_000;

// d3's interpolatePuOr runs purple (0) to orange (1); matplotlib's PuOr, which the Python reference uses, runs
// orange to purple. Reversed here so negative drift is orange and positive is purple in both.
// @types/d3-scale omits constant() on the diverging symlog scale although d3-scale has it; the parity test fails without it.
type SymlogDiverging = ScaleDiverging<string> & { constant(constant: number): SymlogDiverging };

const scale = (scaleDivergingSymlog((t: number) => interpolatePuOr(1 - t)) as SymlogDiverging)
  .constant(LINTHRESH_NS)
  .domain([-CLIP_NS, 0, CLIP_NS])
  .clamp(true);

/** Where a drift in nanoseconds sits on the scale: -1 (saturated negative) to 1 (saturated positive).
 *  Same quantity as the Python `symlog`: sign * log10(1 + |v| / 5) / log10(1 + 10000 / 5), clipped to ±1. */
export function driftPosition(ns: number): number {
  const x = Math.min(Math.max(ns, -CLIP_NS), CLIP_NS);
  return (Math.sign(x) * Math.log1p(Math.abs(x) / LINTHRESH_NS)) / Math.log1p(CLIP_NS / LINTHRESH_NS);
}

/** The fill colour for a drift in nanoseconds, as a CSS `rgb(...)` string. A non-finite value is a bug upstream
 *  (no data is null and never reaches the scale), so it throws rather than quietly drawing as zero. */
export function driftColour(ns: number): string {
  if (!Number.isFinite(ns)) throw new RangeError(`drift must be a finite number of nanoseconds, got ${ns}`);
  return scale(ns);
}

/** Snapshot values are integer tenths of a nanosecond. */
export const tenthsToNs = (tenths: number): number => tenths / 10;
