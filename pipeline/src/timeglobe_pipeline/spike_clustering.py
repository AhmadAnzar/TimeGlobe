"""Phase 1 spike: how crowded is the map? python -m timeglobe_pipeline.spike_clustering"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from timeglobe_pipeline.clustering import BIPM_SEVRES, cluster_sites, radius_km_for_altitude  # noqa: E402
from timeglobe_pipeline.fetch import REPO_ROOT  # noqa: E402
from timeglobe_pipeline.labs import group_sites, load_labs  # noqa: E402
from timeglobe_pipeline.verify_labs import haversine_km  # noqa: E402


def main() -> int:
    labs = load_labs()
    sites = group_sites(labs)
    print(f"{len(labs)} labs on {len(sites)} sites; shared: "
          f"{[s.codes for s in sites if s.count > 1]}")

    print("\nsites within R km of BIPM (Sevres)  [labs / sites]")
    for r in (250, 500, 1000, 1500, 2000, 3000):
        near = [s for s in sites if haversine_km(*BIPM_SEVRES, s.lat, s.lon) <= r]
        print(f"  {r:>5} km: {sum(s.count for s in near):>3} labs / {len(near):>2} sites")

    print("\ndistinct sites closer than 150 km (not merged by the same-city rule):")
    pairs = sorted(
        (haversine_km(a.lat, a.lon, b.lat, b.lon), a, b)
        for i, a in enumerate(sites) for b in sites[i + 1:]
    )
    for km, a, b in pairs:
        if km > 150:
            break
        print(f"  {km:5.0f} km  {'/'.join(a.codes)} ({a.city})  <->  {'/'.join(b.codes)} ({b.city})")

    print("\ncluster counts by radius  [clusters, multi-site clusters, largest]")
    for r in (50, 100, 200, 300, 500, 750, 1000, 1500):
        cl = cluster_sites(sites, r)
        multi = [c for c in cl if len(c.sites) > 1]
        big = max(cl, key=lambda c: c.count)
        print(f"  {r:>5} km: {len(cl):>3} clusters, {len(multi):>2} multi-site, largest {big.count} labs "
              f"around {big.sites[0].city}")

    print("\ncamera altitude -> cluster radius (40 px markers, 800 px canvas, 50 deg FOV)")
    for alt in (2.5, 1.5, 1.0, 0.5, 0.3, 0.15):
        r = radius_km_for_altitude(alt)
        print(f"  altitude {alt:>4}: {r:5.0f} km -> {len(cluster_sites(sites, r)):>3} clusters")

    print("\nEurope detail at 300 km:")
    for c in cluster_sites(sites, 300):
        if len(c.sites) > 1 and 34 < c.lat < 62 and -12 < c.lon < 45:
            print(f"  {c.count:>2} labs near ({c.lat:.1f}, {c.lon:.1f}): {', '.join(c.codes)}")

    fig, ax = plt.subplots(figsize=(9, 8))
    for s in sites:
        if 33 < s.lat < 63 and -12 < s.lon < 48:
            ax.scatter(s.lon, s.lat, s=40 + 25 * s.count, color="#2b6cb0", zorder=3)
            ax.annotate("/".join(s.codes), (s.lon, s.lat), fontsize=6, xytext=(3, 3), textcoords="offset points")
    lat0, lon0 = BIPM_SEVRES
    ax.scatter(lon0, lat0, marker="*", s=200, color="#c05621", zorder=4)
    for r in (500, 1000, 2000):
        angle = np.linspace(0, 2 * np.pi, 200)
        ax.plot(lon0 + r / (111.0 * np.cos(np.radians(lat0))) * np.cos(angle),
                lat0 + r / 111.0 * np.sin(angle), linestyle="--", color="#999999")
        ax.annotate(f"{r} km", (lon0, lat0 + r / 111.0), fontsize=7, color="#666666")
    ax.set_aspect(1 / np.cos(np.radians(48)))
    ax.set_xlim(-12, 48), ax.set_ylim(33, 63)
    ax.set_title("European lab sites (star = BIPM, Sevres; rings 500/1000/2000 km)")
    out = REPO_ROOT / "pipeline" / "out" / "europe_sites.png"
    fig.savefig(out, dpi=130, bbox_inches="tight")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
