const MJD_EPOCH_MS = Date.UTC(1858, 10, 17); // MJD 0 is 1858-11-17
const DAY_MS = 86_400_000;

export function mjdToDate(mjd: number): Date {
  return new Date(MJD_EPOCH_MS + mjd * DAY_MS);
}

/** "2026-09-26" for MJD 61309. */
export function mjdToIso(mjd: number): string {
  return mjdToDate(mjd).toISOString().slice(0, 10);
}
