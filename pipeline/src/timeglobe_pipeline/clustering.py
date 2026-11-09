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
