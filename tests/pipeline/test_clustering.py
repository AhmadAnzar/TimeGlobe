import pytest

from timeglobe_pipeline.clustering import (
    ALTITUDE_BUCKETS,
    CAP_KM,
    bucket_radius_km,
    bucket_ranges,
    cluster_sites,
    precompute,
    radius_km_for_altitude,
)
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


# --- precomputed buckets (what clusters.json ships) -------------------------------------------


@pytest.fixture(scope="module")
def buckets(sites):
    ordered = sorted(sites, key=lambda s: s.codes)
    return precompute(ordered, {s.codes: i for i, s in enumerate(ordered)})


def test_there_are_eight_buckets_with_falling_altitude_and_radius(buckets):
    assert len(buckets) == len(ALTITUDE_BUCKETS) == 8
    assert [b["altitude"] for b in buckets] == sorted(ALTITUDE_BUCKETS, reverse=True)
    radii = [b["radius_km"] for b in buckets]
    assert radii == sorted(radii, reverse=True) and len(set(radii)) == 8  # every bucket differs
    assert radii[0] == CAP_KM == 500.0  # the default 2.5 altitude would be 743 km: capped


def test_the_top_bucket_reproduces_the_capped_analysis(sites, buckets):
    top = buckets[0]
    assert len(cluster_sites(sites, 500.0)) == 51 and len(top["clusters"]) == 17
    assert max(len(c["labs"]) for c in top["clusters"]) == 10  # Bruxelles region, as analysed


def test_the_other_buckets_match_the_analysis_cluster_counts(sites):
    counts = {alt: len(cluster_sites(sites, bucket_radius_km(alt))) for alt in (1.0, 0.5, 0.3)}
    assert counts == {1.0: 60, 0.5: 82, 0.3: 84}


def test_only_multi_site_clusters_are_listed_and_no_lab_is_in_two(buckets):
    for bucket in buckets:
        seen = set()
        for cluster in bucket["clusters"]:
            assert len(cluster["sites"]) >= 2  # a shared-city site is one point, never a cluster
            assert not seen & set(cluster["labs"])
            seen |= set(cluster["labs"])


def test_cluster_site_ids_point_at_the_sites_that_hold_the_labs(sites, buckets):
    ordered = sorted(sites, key=lambda s: s.codes)
    for bucket in buckets:
        for cluster in bucket["clusters"]:
            from_sites = sorted(code for i in cluster["sites"] for code in ordered[i].codes)
            assert from_sites == cluster["labs"]


def test_bucket_ranges_tile_the_altitude_axis_without_gaps():
    ranges = bucket_ranges()
    assert ranges[0][2] is None and ranges[-1][1] == 0.0
    for (_, lower, _), (_, _, upper) in zip(ranges, ranges[1:]):
        assert lower == upper  # one bucket ends where the next begins
    for alt, lower, upper in ranges:
        assert lower <= alt and (upper is None or alt < upper)


def test_precompute_is_deterministic(sites):
    ordered = sorted(sites, key=lambda s: s.codes)
    ids = {s.codes: i for i, s in enumerate(ordered)}
    assert precompute(ordered, ids) == precompute(list(reversed(ordered)), ids)
