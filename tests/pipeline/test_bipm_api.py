import json
from pathlib import Path

import pytest

from timeglobe_pipeline.bipm_api import ApiError, parse_gnss, parse_labs, parse_series

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_parse_labs_uppercases_codes():
    labs = parse_labs((FIXTURES / "bipm_labs.json").read_bytes())
    assert len(labs) == 98
    assert labs[:3] == ["AGGO", "AOS", "APL"]
    assert "NIST" in labs


def test_parse_series_nist_full_record():
    (series,) = parse_series((FIXTURES / "bipm_utc_nist.json").read_bytes())
    assert series.name == "UTC-UTC(NIST)"
    assert len(series.mjd) == len(series.value_ns) == len(series.unc_ns) == 2100
    assert series.mjd[0] == 50814  # 1998-01-01
    assert series.mjd[-1] == 61309
    assert series.value_ns[-5:] == [-0.4, -0.3, 0.4, 1.0, 0.9]


def test_uncertainties_are_null_before_2007_and_floats_after():
    (series,) = parse_series((FIXTURES / "bipm_utc_nist.json").read_bytes())
    first = next(i for i, u in enumerate(series.unc_ns) if u is not None)
    assert series.mjd[first] == 54074
    assert all(u is None for u in series.unc_ns[:first])
    assert series.unc_ns[-1] == 2.1


def test_dash_uncertainty_means_none_not_an_error():
    # APL's published uncertainty is "-" (not computed) from 2024 on.
    (series,) = parse_series((FIXTURES / "bipm_utc_apl.json").read_bytes())
    assert series.unc_ns[-1] is None
    assert any(u is not None for u in series.unc_ns)
    assert len(series.unc_ns) == len(series.value_ns)


def test_junk_uncertainty_labels_become_none_and_are_reported():
    # AZ's real response has "AZ" and "CirT.453" in the uncertainty field.
    (series,) = parse_series((FIXTURES / "bipm_utc_az.json").read_bytes())
    junk = {raw for _, raw in series.unc_unparsed}
    assert junk == {"AZ", "CirT.453"}
    assert len(series.unc_unparsed) == 44
    flagged = {mjd for mjd, _ in series.unc_unparsed}
    assert all(u is None for mjd, u in zip(series.mjd, series.unc_ns) if mjd in flagged)
    assert any(u is not None for u in series.unc_ns)  # real numbers still parsed


def test_sparse_lab_has_gaps_and_large_values():
    (series,) = parse_series((FIXTURES / "bipm_utc_kebs.json").read_bytes())
    steps = {b - a for a, b in zip(series.mjd, series.mjd[1:])}
    assert max(steps) > 5  # gaps stay gaps, nothing is filled in
    assert min(series.value_ns) < -90_000  # microsecond-scale drift exists


def test_api_error_raises():
    body = json.dumps({"success": False, "errorcode": 4, "message": "bad query"}).encode()
    with pytest.raises(ApiError, match="bad query"):
        parse_series(body)


def test_ragged_series_rejected():
    body = json.dumps(
        {
            "success": True,
            "data": [{"name": "UTC-UTC(X)", "x": [1, 2], "y": [1.0], "unc": [None, None]}],
        }
    ).encode()
    with pytest.raises(ApiError, match="ragged"):
        parse_series(body)


def test_gnss_response_has_four_daily_systems_with_numeric_uncertainties():
    gnss = parse_gnss((FIXTURES / "bipm_gnss.json").read_bytes())
    assert sorted(gnss) == ["beidou", "galileo", "glonass", "gps"]
    gps = gnss["gps"]
    assert (gps.mjd[0], gps.mjd[-1], len(gps.mjd)) == (55559, 61309, 5751)  # one value per day
    assert gps.unc_ns[:2] == [1.4, 1.4] and gps.unc_ns[-1] == 5.0
    assert (gnss["galileo"].mjd[0], gnss["beidou"].mjd[0]) == (60430, 60430)
    assert all(not s.unc_unparsed for s in gnss.values())


def test_gnss_metadata_is_scrambled_so_ranges_come_from_the_arrays():
    import json

    raw = json.loads((FIXTURES / "bipm_gnss.json").read_bytes())
    glonass = next(s for s in raw["data"] if s["name"] == "UTC-GLONASS_Time")
    assert glonass["xmax"] == 5 and glonass["ymax"] == 61309  # swapped in the source
    parsed = parse_gnss((FIXTURES / "bipm_gnss.json").read_bytes())["glonass"]
    assert (parsed.mjd[0], parsed.mjd[-1]) == (55559, 61309)


def test_unexpected_gnss_series_name_is_an_error():
    body = json.dumps(
        {"success": True, "data": [{"name": "UTC-Other", "x": [1], "y": [1.0], "unc": [None]}]}
    ).encode()
    with pytest.raises(ApiError, match="unexpected GNSS series"):
        parse_gnss(body)


def test_rapid_utc_is_daily_with_no_uncertainties_and_keeps_its_gap():
    (nist,) = parse_series((FIXTURES / "bipm_utcr_nist.json").read_bytes())
    assert nist.name == "UTCR-UTC(NIST)"
    assert (nist.mjd[0], nist.mjd[-1], len(nist.mjd)) == (56467, 61345, 4878)
    assert all(u is None for u in nist.unc_ns)
    steps = {b - a for a, b in zip(nist.mjd, nist.mjd[1:])}
    assert steps == {1, 2}  # one missing day stays missing
    (uz,) = parse_series((FIXTURES / "bipm_utcr_uz.json").read_bytes())
    assert uz.mjd[0] == 60289 and len(uz.mjd) == 1056
