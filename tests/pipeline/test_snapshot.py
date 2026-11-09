import json
from dataclasses import replace
from pathlib import Path

import pytest

from timeglobe_pipeline import circular_t_index
from timeglobe_pipeline.bipm_api import parse_gnss, parse_series
from timeglobe_pipeline.circular_t import parse_section1
from timeglobe_pipeline.clock_list import active_counts, parse_clocks
from timeglobe_pipeline.labs import load_labs
from timeglobe_pipeline.prepare import prepare_series
from timeglobe_pipeline.snapshot import (
    SnapshotInput,
    build_snapshot,
    initial_payload_gzip,
    sizes,
    tenths,
    year_of,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
LABS = ["NIST", "APL", "KEBS", "AZ"]


@pytest.fixture(scope="module")
def data():
    labs = load_labs()
    known = {lab.code for lab in labs}
    sections = [
        parse_section1((FIXTURES / f"cirt.{n}").read_bytes().decode()) for n in range(453, 466)
    ]
    series, sources, flags = {}, {}, {}
    for code in LABS:
        (api,) = parse_series((FIXTURES / f"bipm_utc_{code.lower()}.json").read_bytes())
        prepared = prepare_series(code, api, sections, known)
        series[code], sources[code], flags[code] = prepared.series, prepared.source, prepared.flags
    clocks, other = active_counts(
        parse_clocks((FIXTURES / "bipm_clocklab.html").read_bytes().decode()), known
    )
    index = circular_t_index.parse_md5sums((FIXTURES / "cirt_MD5SUMS").read_text())
    rapid = {
        code: parse_series((FIXTURES / f"bipm_utcr_{code.lower()}.json").read_bytes())[0]
        for code in ("NIST", "UZ")
    }
    return SnapshotInput(
        labs=labs, series=series, sources=sources,
        gnss=parse_gnss((FIXTURES / "bipm_gnss.json").read_bytes()),
        clocks=clocks, circular_t_latest=circular_t_index.latest_issue(index),
        generated_at="2026-11-09", flags=flags, unmapped_clocks=other, rapid=rapid,
    )


@pytest.fixture(scope="module")
def files(data):
    return build_snapshot(data)


def load(files, path):
    return json.loads(files[path])


def test_files_present(files):
    assert {"meta.json", "labs.json", "gnss.json"} <= set(files)
    assert all(f"labs/{c}.json" in files for c in LABS)
    assert "frames/1998.json" in files and "frames/2026.json" in files
    assert not any(p.startswith("labs/") and p[5:-5] not in LABS for p in files)


def test_output_is_deterministic(data, files):
    assert build_snapshot(data) == files


def test_tenths_packs_exactly_and_rejects_off_grid_values():
    assert [tenths(v) for v in (0.0, -0.3, 7.1, 95504.5, -95504.5)] == [0, -3, 71, 955045, -955045]
    with pytest.raises(ValueError):
        tenths(0.15)


def test_frames_use_null_for_no_data_never_zero(files):
    frame = load(files, "frames/1998.json")
    labs = frame["labs"]
    assert labs == sorted(labs)
    row = frame["v"][0]
    assert row[labs.index("NIST")] == 0  # a real 0.0 at MJD 50814 stays 0
    assert row[labs.index("AZ")] is None and row[labs.index("USNO")] is None
    assert row[labs.index("KEBS")] is None  # KEBS only starts in 2012


def test_a_labs_gaps_stay_gaps(files):
    kebs = labs_detail(files, "KEBS")
    steps = {b - a for a, b in zip(kebs["mjd"], kebs["mjd"][1:])}
    assert max(steps) > 5
    frame = load(files, "frames/2017.json")
    col = frame["labs"].index("KEBS")
    assert all(row[col] is None for row in frame["v"])  # KEBS stopped in 2016


def labs_detail(files, code):
    return load(files, f"labs/{code}.json")


def test_uncertainty_is_null_before_it_was_published(files):
    nist = labs_detail(files, "NIST")
    first = next(i for i, u in enumerate(nist["u"]) if u is not None)
    assert nist["mjd"][first] == 54074
    assert all(u is None for u in nist["u"][:first])
    assert nist["u"][-1] == 21  # 2.1 ns in tenths


def test_az_comes_from_circular_t_with_its_70_values(files):
    az = labs_detail(files, "AZ")
    assert az["source"] == "circular_t" and len(az["mjd"]) == 70
    assert (az["mjd"][0], az["v"][0]) == (60949, 2399)
    assert labs_detail(files, "NIST")["source"] == "api"


def test_labs_json_has_bipm_text_sites_and_clocks(files):
    doc = load(files, "labs.json")
    by_code = {lab["code"]: lab for lab in doc["labs"]}
    assert len(by_code) == 98
    assert by_code["BIRM"]["country"] == "P.R. China" and by_code["BIRM"]["iso2"] == "CN"
    assert by_code["BIRM"]["site"] == by_code["NIM"]["site"]
    site = doc["sites"][by_code["IGNA"]["site"]]
    assert site["labs"] == ["IGNA", "INTI", "ONBA"]
    assert by_code["USNO"]["clocks"] == 63 and by_code["AOS"]["clocks"] == 0
    assert by_code["NIST"]["has_data"] and not by_code["USNO"]["has_data"]  # only 4 labs loaded


def test_gnss_has_all_four_systems_in_tenths(files):
    gnss = load(files, "gnss.json")
    assert sorted(gnss) == ["beidou", "galileo", "glonass", "gps"]
    assert gnss["gps"]["mjd"][0] == 55559 and gnss["gps"]["v"][0] == -93
    assert gnss["galileo"]["mjd"][0] == 60430


def test_meta_records_freshness_counts_flags_and_attribution(files):
    meta = load(files, "meta.json")
    assert meta["circular_t_latest"] == 465 and meta["generated_at"] == "2026-11-09"
    assert meta["labs"] == 98 and meta["labs_with_data"] == 4
    assert meta["values"] == 2100 + 1840 + 263 + 70  # NIST + APL + KEBS + AZ (Circular T)
    assert (meta["mjd_first"], meta["mjd_last"]) == (50814, 61309)
    assert "Not affiliated with or endorsed by BIPM" in meta["attribution"]
    assert meta["flags"]["AZ"][0].startswith("rebuilt from Circular T issues 454-465")
    assert meta["years"][0] == 1998 and meta["years"][-1] == 2026


def test_year_of_and_size_helpers(files):
    assert year_of(50814) == 1998 and year_of(61309) == 2026
    table = sizes(files)
    assert all(gz <= raw for raw, gz in table.values() if raw > 1000)
    assert initial_payload_gzip(files) < 300 * 1024


def test_clock_totals_are_computed_from_the_inputs_not_stored(data, files):
    clocks = load(files, "meta.json")["clocks"]
    assert clocks["in_labs"] == sum(data.clocks.values())
    assert clocks["unmapped"] == data.unmapped_clocks
    assert clocks["total"] == clocks["in_labs"] + sum(data.unmapped_clocks.values())
    assert clocks["definition"] == "clocks not marked stopped on the Time Database clock list"
    # a lab's own size never includes clocks filed under a non-lab code such as "F"
    labs = load(files, "labs.json")["labs"]
    assert sum(lab["clocks"] for lab in labs) == clocks["in_labs"] < clocks["total"]


def test_changing_the_clock_input_changes_the_total(data):
    fewer = replace(data, clocks={**data.clocks, "USNO": 1}, unmapped_clocks={})
    meta = json.loads(build_snapshot(fewer)["meta.json"])["clocks"]
    assert meta["total"] == meta["in_labs"] == sum(fewer.clocks.values())


def test_rapid_values_are_only_those_after_the_latest_circular_t_date_and_provisional(files):
    nist = labs_detail(files, "NIST")
    rapid = nist["rapid"]
    latest = max(nist["mjd"])
    assert rapid["provisional"] is True
    assert min(rapid["mjd"]) == latest + 1 and max(rapid["mjd"]) == 61345
    assert len(rapid["mjd"]) == 36
    assert all(u is None for u in rapid["u"])  # rapid values carry no uncertainty
    assert "rapid" not in labs_detail(files, "APL")  # no rapid data given for APL


def test_meta_says_rapid_values_are_provisional_and_after_which_date(files):
    meta = load(files, "meta.json")
    assert meta["rapid"] == {"provisional": True, "after_mjd": 61309, "labs": 1}


def test_rapid_data_with_no_published_series_is_ignored_and_flagged(files):
    assert "UZ" not in {p[5:-5] for p in files if p.startswith("labs/")}
    flag = load(files, "meta.json")["flags"]["UZ"]
    assert flag == ["rapid values ignored: no published series"]


def test_rapid_values_already_covered_by_circular_t_leave_no_rapid_block(data):
    nist = data.rapid["NIST"]
    covered = type(nist)(nist.name, nist.mjd[:100], nist.value_ns[:100], nist.unc_ns[:100])
    out = json.loads(build_snapshot(replace(data, rapid={"NIST": covered}))["labs/NIST.json"])
    assert "rapid" not in out
