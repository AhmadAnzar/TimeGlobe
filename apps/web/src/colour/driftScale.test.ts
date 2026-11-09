import { describe, expect, it } from "vitest";
import golden from "./golden.json";
import { CLIP_NS, LINTHRESH_NS, driftColour, driftPosition, tenthsToNs } from "./driftScale";

/** "#rrggbb" or "rgb(r, g, b)" to its three 8-bit channels. */
const channels = (colour: string): [number, number, number] => {
  const [r = NaN, g = NaN, b] =
    colour.startsWith("#")
      ? [1, 3, 5].map((i) => Number.parseInt(colour.slice(i, i + 2), 16))
      : (colour.match(/\d+/g) ?? []).slice(0, 3).map(Number);
  return [r, g, b ?? NaN];
};

// d3 blends the 11 PuOr colours with a B-spline and matplotlib blends them linearly, so the two agree at the
// saturated ends and differ slightly in between. Measured against the golden values: the largest gap is 13 of 255
// (at 0 ns, the pale middle: d3 rgb(243, 238, 234) against matplotlib #f6f6f7). The bound is that measurement,
// so it will fail if the scale or the palette changes.
const MAX_CHANNEL_DIFF = 13;

describe("drift scale parity with the Python reference", () => {
  it("uses the same constants as the golden file", () => {
    expect(LINTHRESH_NS).toBe(golden.linthresh_ns);
    expect(CLIP_NS).toBe(golden.clip_ns);
  });

  it.each(golden.rows)("position of $ns ns matches Python", ({ ns, position }) => {
    expect(driftPosition(ns)).toBeCloseTo(position, 12);
  });

  it.each(golden.rows)("colour of $ns ns is within the measured tolerance of Python's", ({ ns, hex }) => {
    const got = channels(driftColour(ns));
    const want = channels(hex);
    got.forEach((value, i) => expect(Math.abs(value - want[i]!)).toBeLessThanOrEqual(MAX_CHANNEL_DIFF));
  });

  it("is exact at the saturated ends and beyond them", () => {
    for (const row of golden.rows.filter((r) => Math.abs(r.ns) >= CLIP_NS)) {
      expect(channels(driftColour(row.ns))).toEqual(channels(row.hex));
    }
  });

});

describe("driftColour", () => {
  it("puts negative drift on the orange side and positive on the purple side, as the Python scale does", () => {
    const [nr, , nb] = channels(driftColour(-1000));
    const [pr, , pb] = channels(driftColour(1000));
    expect(nr).toBeGreaterThan(nb);
    expect(pb).toBeGreaterThan(pr);
  });

  it("is the pale middle at zero", () => {
    expect(Math.min(...channels(driftColour(0)))).toBeGreaterThan(220);
  });

  it("is linear-ish inside ±5 ns: 1 ns and 2 ns are distinguishable, not collapsed", () => {
    expect(driftColour(1)).not.toBe(driftColour(2));
    expect(driftColour(1)).not.toBe(driftColour(0));
  });

  it("refuses a value that is not a number instead of drawing it as zero", () => {
    expect(() => driftColour(Number.NaN)).toThrow(RangeError);
    expect(() => driftColour(Number.POSITIVE_INFINITY)).toThrow(RangeError);
  });
});

describe("tenthsToNs", () => {
  it("converts the snapshot's integer tenths", () => {
    expect(tenthsToNs(0)).toBe(0);
    expect(tenthsToNs(-123)).toBe(-12.3);
  });
});
