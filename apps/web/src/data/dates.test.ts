import { describe, expect, it } from "vitest";
import { mjdToIso } from "./dates";

describe("mjdToIso", () => {
  it("converts the dates the pipeline documents", () => {
    expect(mjdToIso(50814)).toBe("1998-01-01"); // first value of the 5-day series
    expect(mjdToIso(54074)).toBe("2006-12-05"); // first published uncertainty
    expect(mjdToIso(61309)).toBe("2026-09-26"); // latest Circular T date at the time of writing
  });

  it("is MJD 0 at 1858-11-17", () => {
    expect(mjdToIso(0)).toBe("1858-11-17");
  });
});
