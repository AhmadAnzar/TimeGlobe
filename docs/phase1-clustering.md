# Phase 1: Europe and shared-city clustering

How crowded is the map, and how should crowded places be drawn? Source: `pipeline/data/labs.csv`
(98 labs). Reproduce with `python -m timeglobe_pipeline.spike_clustering`, which also draws a
map of the European sites.

## Facts

- 98 labs sit on **90 sites**. 7 sites hold several labs: Buenos Aires has 3, and Beijing, Hong Kong,
  Lintong, Rio de Janeiro, Washington DC and Bruxelles have 2 each.
- BIPM (Sèvres) has exactly one lab within 250 km (OP, in Paris). Within 500 km there are 9 labs, within
  1,000 km 18, within 2,000 km 44, within 3,000 km 47. **44 of the 98 labs (45%) lie inside a
  2,000 km disc around Sèvres**, so 44 flow arcs converge on one point, and the pile-up happens in the
  last ~1,000 km.
- Distinct sites that still nearly collide (not merged by the same-city rule): ESA/VSL 26 km,
  APL/Washington 28 km, AGGO/Buenos Aires 53 km, BEV/SMU 55 km, NICT/NMIJ 67 km.
- Greedy clustering (the site with the most labs seeds a cluster and takes every unassigned site
  within the radius):

| Radius | Clusters | Multi-site clusters | Largest cluster |
|---|---|---|---|
| 50 km | 88 | 2 | 3 labs (Buenos Aires) |
| 150 km | 82 | | |
| 300 km | 60 | 16 | 8 labs (Wien region) |
| 500 km | 51 | 17 | 10 labs (Bruxelles region) |
| 750 km | 44 | 14 | 15 labs |
| 1,000 km | 36 | 15 | 24 labs |

  At 300 km the Low Countries cluster is ESA, LUX, OP, ORB, SMD, VSL, and the Central Europe cluster is
  BEV, BFKH, IFAG, IFZG, SIQ, SMU, TP, TUG.

## Rules

1. **The cluster radius follows camera altitude, capped.** About 300 km × altitude, assuming 40 px
   markers, an 800 px canvas and a 50° field of view (altitude 2.5 → 743 km, 1.0 → 297 km, 0.3 →
   89 km), **capped at 500 km** so that Europe never collapses into a cluster larger than 10 labs.
   Fully zoomed out that is about 51 clusters. Below altitude ~0.3 nearly every lab is individual again.
   These constants are approximations to tune on the real globe.
2. **Algorithm:** greedy by lab count (`clustering.cluster_sites`, tested). Single linkage would chain
   Europe into one cluster.
3. **A cluster is a neutral-filled point with a count badge. It is never coloured by drift.** Its
   tooltip lists each lab and that lab's value. Clicking it flies in until it splits. Labs that share
   a city are always one site and follow the same display rule.
4. **Arcs to Sèvres fade with distance**, for example full opacity beyond ~2,000 km, falling to
   ~15% inside ~300 km, so the last stretch does not saturate. Arcs are drawn per lab, not per cluster.
