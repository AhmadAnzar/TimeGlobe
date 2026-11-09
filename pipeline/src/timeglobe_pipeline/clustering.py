"""Distance-based clustering of map sites, for the "cluster when zoomed out" rule.

Greedy and deterministic: the site with the most labs (then the alphabetically first code) seeds a
cluster and takes every unassigned site within radius_km of it. Unlike single linkage, a chain of
nearby sites cannot snowball into one huge cluster.
"""

import math
from dataclasses import dataclass

from timeglobe_pipeline.labs import Site
from timeglobe_pipeline.verify_labs import haversine_km

BIPM_SEVRES = (48.83, 2.22)  # Pavillon de Breteuil, Sèvres: the target of the flow arcs


@dataclass(frozen=True)
class Cluster:
    lat: float
    lon: float
    sites: tuple[Site, ...]

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(sorted(code for site in self.sites for code in site.codes))

    @property
    def count(self) -> int:
        return len(self.codes)


def _centroid(sites: tuple[Site, ...]) -> tuple[float, float]:
    """Mean on the sphere (3D vectors), so clusters across the antimeridian stay correct."""
    x = y = z = 0.0
    for site in sites:
        lat, lon = math.radians(site.lat), math.radians(site.lon)
        weight = site.count
        x += weight * math.cos(lat) * math.cos(lon)
        y += weight * math.cos(lat) * math.sin(lon)
        z += weight * math.sin(lat)
    return math.degrees(math.atan2(z, math.hypot(x, y))), math.degrees(math.atan2(y, x))


def cluster_sites(sites: list[Site], radius_km: float) -> list[Cluster]:
    remaining = sorted(sites, key=lambda s: (-s.count, s.codes))
    clusters = []
    while remaining:
        seed = remaining[0]
        members = tuple(
            s for s in remaining if s is seed or haversine_km(seed.lat, seed.lon, s.lat, s.lon) <= radius_km
        )
        remaining = [s for s in remaining if s not in members]
        lat, lon = _centroid(members)
        clusters.append(Cluster(lat, lon, members))
    return clusters


def radius_km_for_altitude(altitude: float, marker_px: float = 40.0, canvas_px: float = 800.0,
                           fov_deg: float = 50.0) -> float:
    """Approximate ground distance covered by marker_px at the centre of the view for a camera
    `altitude` globe radii above the surface. Assumptions are stated so phase 3 can tune them."""
    visible_radii = 2 * altitude * math.tan(math.radians(fov_deg / 2))
    return 6371.0 * visible_radii * marker_px / canvas_px


# --- precomputed buckets: the web app only reads these, it does not cluster ---------------------

CAP_KM = 500.0  # a cluster radius never exceeds this, so Europe cannot collapse into one blob
# Camera altitudes (globe radii above the surface) the clusters are computed for; globe.gl's
# default view is 2.5. Chosen so every bucket has a different radius under the cap.
ALTITUDE_BUCKETS = (2.5, 1.4, 1.0, 0.7, 0.5, 0.3, 0.2, 0.1)


def bucket_radius_km(altitude: float) -> float:
    return min(radius_km_for_altitude(altitude), CAP_KM)


def bucket_ranges() -> list[tuple[float, float, float | None]]:
    """(altitude, min_altitude, max_altitude) per bucket, largest altitude first. A bucket serves
    the altitudes between the midpoints to its neighbours: the first has no upper bound and the
    last runs down to 0."""
    alts = list(ALTITUDE_BUCKETS)
    out = []
    for i, alt in enumerate(alts):
        upper = None if i == 0 else round((alts[i - 1] + alt) / 2, 3)
        lower = 0.0 if i == len(alts) - 1 else round((alt + alts[i + 1]) / 2, 3)
        out.append((alt, lower, upper))
    return out


def precompute(sites: list[Site], site_ids: dict[tuple[str, ...], int]) -> list[dict]:
    """The clusters for every altitude bucket as JSON-ready dicts. Only clusters of two or more
    sites are listed: a site that is in none is drawn on its own, and a shared-city site is always
    one point, never a cluster. site_ids maps a site's lab codes to its id in labs.json."""
    buckets = []
    for altitude, lower, upper in bucket_ranges():
        radius = bucket_radius_km(altitude)
        clusters = [
            {
                "lat": round(c.lat, 4),
                "lon": round(c.lon, 4),
                "labs": list(c.codes),
                "sites": sorted(site_ids[s.codes] for s in c.sites),
            }
            for c in cluster_sites(sites, radius)
            if len(c.sites) > 1
        ]
        clusters.sort(key=lambda c: c["labs"])
        buckets.append(
            {
                "altitude": altitude,
                "radius_km": round(radius, 1),
                "min_altitude": lower,
                "max_altitude": upper,
                "clusters": clusters,
            }
        )
    return buckets
