# Phase 1: data findings

What the BIPM data looks like, as examined on 9 November 2026 (Circular T 465 is the latest
issue). Each figure below can be reproduced with the modules in `pipeline/`; the real responses
the tests use are saved in `tests/fixtures/`.

## Sources

| Source | What it gives |
|---|---|
| BIPM API v1.0 (`get-data.html`) | UTC-UTC(k) per lab as JSON, CSV or text, with uncertainties; the list of lab codes (`list`) |
| Circular T, Section 1 | The same quantity for the latest issue, with each lab's city and uA, uB and u uncertainties |
| BIPM Time Database, `showlab.html` | One table of every lab that ever took part: name, city, country, start and stop year |
| NTP Pool zone pages | Server counts per country (no data API was found) |

## The drift series

- The API lists **98 laboratories**; **97 have values**, **133,951 in total**. EE joined in 2026 and
  has none yet.
- Every value sits on one 5-day grid, from MJD 50814 (1998-01-01) to MJD 61309 (2026-09-26).
- **Coverage varies a lot.** A typical lab has values on 78% of the 2,100 dates since 1998 (median);
  75 of 97 labs have at least 90% of the dates inside their own reporting span. The longest gap is
  215 days. 83 labs have a value in the latest issue.
- **Uncertainties exist only from MJD 54074 (2006-12-05).** Before that the API sends `null`. Since
  2024 some labs (for example APL, CAO, IDN, INM, LRTE) send `"-"` again, meaning "not computed".
- **Values span a huge range.** The median |value| is 23 ns, but the history reaches -95,504 ns
  (KEBS) and several labs sit in the thousands of ns in the latest issue. Linear colour scales fail
  on this data.
- **A value of exactly `0.0` is real.** 759 genuine zeros occur in 61 labs (USNO 55, NIST 52,
  TUG 43, SU 40, OP 39). Zero is only suspicious when it appears as repeated blocks on repeated dates.

## The 98 laboratories

| Status | Count | Meaning |
|---|---|---|
| current | 87 | Listed in Circular T 465 Section 1 |
| former | 9 | Stopped reporting: BOM, EIM, IGNA, KEBS, LDS, LV, SL, TUG, UTE |
| not in the latest issue | 2 | EE (joined 2026, no data yet) and MASM (still participating, last value 2025-04) |

NRL and NSAI are in the latest issue but have had no recent values. The API's own lab list is codes
only; names, cities, countries and years come from the Time Database table.

## Data problems the pipeline has to handle

- **The API series for AZ is malformed.** It repeats blocks of the same dates (60919, 60929, 60939,
  then 60919 again), carries `0.0` placeholders on them, and has 44 uncertainty entries that are
  labels (`"AZ"`, `"CirT.453"`) instead of numbers: 136 duplicate dates in 212 rows, with dates going
  backwards 43 times.
- **MIKE** has one junk uncertainty entry (`"main"`).
- The lab-list response has no `success` field; data responses do.
- **Circular T and the API agree on AZ.** AZ first appears in issue **454** (issue 453 has no AZ row).
  The 70 distinct AZ dates in issues 454-465 (MJD 60949-61294) all appear in the API with identical
  values and uncertainties. Six API-only dates (MJD 60919-60944, September 2025) precede AZ's first
  Circular T row and have no published counterpart; each carries a plausible value (212-232 ns) and
  three also carry `0.0` placeholders.
- **How the pipeline handles it:** a series whose dates repeat or run backwards is rebuilt from the
  published Circular T issues (`reconcile.rebuild_from_circular_t`). For AZ that is 70 values from
  issues 454-465; the six unpublished API-only points are excluded and flagged.
- **Circular T layout details:** issue 454 has 8 date columns instead of 7, a row can carry a
  multi-note marker such as `(1,2)`, and consecutive issues share their boundary date with the same
  value (for example 2025-11-30 in issues 455 and 456).
- The pipeline reports series problems (duplicate or backward dates, off-grid dates, absurd values,
  junk uncertainty labels) and never repairs them silently (`validate.check_series`).

## Colour scale

Symmetric log: linear within ±5 ns, logarithmic beyond, saturating at ±10,000 ns. With a ±1,000 ns
clip, 15% of all values saturate; at ±10,000 ns only 2.2% do. The palette is the diverging
purple-orange PuOr. Near-zero values get a pale fill with a thin dark outline; a lab with no value at
a date is a hollow dashed ring, never zero.

`python -m timeglobe_pipeline.spike_coverage` draws the per-lab coverage chart and the scale study.

## Coordinates

Lab coordinates are entered by hand at city level in `pipeline/data/labs.csv`, together with each
lab's ISO country code, and checked against OpenStreetMap Nominatim (90 distinct queries, at most one
per second): the median distance is 1 km, and 94 of 98 labs are within 50 km. Four are further:

| Lab | Distance | Reason |
|---|---|---|
| AOS | 247 km | Nominatim picked a different "Borowiec" (Pomerania); the lab is near Poznań |
| APL | 673 km | It picked Laurel County, Kentucky; the lab is in Laurel, Maryland |
| CNM | 58 km | Querétaro city centre against the municipality centre |
| TL | 105 km | It picked a place in Taichung; Chung-Li is in Taoyuan |

Countries are stored exactly as BIPM's lab table writes them ("P.R. China", "Chinese Taipei",
"Russian Federation"...) next to an ISO code, and a test checks every row against the table. BIPM
lists Hong Kong as its own country, so HKO and SCL are `HK` although OpenStreetMap files Hong Kong
under CN. Seven cities host more than one lab (six pairs and one trio, Buenos Aires), so they share
one point. See [the clustering analysis](phase1-clustering.md).

## NTP Pool

The global zone page links the 7 continent pages; each lists every country zone with its server
count: 251 zones, 127 with servers. The pool names the United Kingdom `uk`, while ISO uses `GB`.

---

Time data: © BIPM Time Department (Circular T, API, Time Database), licensed under CC BY 4.0.
Processed by the Time Globe project; not affiliated with or endorsed by BIPM. Geocoding ©
OpenStreetMap contributors. NTP server counts: NTP Pool Project.
