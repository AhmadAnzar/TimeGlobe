import pytest

from timeglobe_pipeline.clustering import cluster_sites, radius_km_for_altitude
from timeglobe_pipeline.labs import group_sites, load_labs


@pytest.fixture(scope="module")
def sites():
    return group_sites(load_labs())


def test_zero_radius_keeps_every_site_separate(sites):
    clusters = cluster_sites(sites, 0)
    assert len(clusters) == len(sites) == 90


def test_huge_radius_gives_one_cluster_with_every_lab(sites):
    (cluster,) = cluster_sites(sites, 40_000)
    assert cluster.count == 98


def test_every_lab_is_in_exactly_one_cluster(sites):
    for radius in (50, 300, 1000):
        codes = [code for c in cluster_sites(sites, radius) for code in c.codes]
        assert sorted(codes) == sorted(set(codes)) and len(codes) == 98


def test_low_countries_labs_cluster_at_300_km(sites):
    clusters = {c.codes: c for c in cluster_sites(sites, 300)}
    low = clusters[("ESA", "LUX", "OP", "ORB", "SMD", "VSL")]
    assert 49 < low.lat < 52 and 3 < low.lon < 6


def test_chain_of_nearby_sites_does_not_snowball(sites):
    # Single linkage would chain Europe into one blob at 300 km; the greedy rule must not.
    assert max(c.count for c in cluster_sites(sites, 300)) <= 8


def test_clusters_are_deterministic(sites):
    first = [c.codes for c in cluster_sites(sites, 300)]
    assert first == [c.codes for c in cluster_sites(list(reversed(sites)), 300)]


def test_cluster_radius_grows_with_altitude():
    assert radius_km_for_altitude(2.5) > radius_km_for_altitude(1.0) > radius_km_for_altitude(0.2)
    assert radius_km_for_altitude(1.0) == pytest.approx(297, abs=3)
