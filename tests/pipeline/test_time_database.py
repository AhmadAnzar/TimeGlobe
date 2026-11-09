from pathlib import Path

import pytest

from timeglobe_pipeline.bipm_api import parse_labs as parse_api_labs
from timeglobe_pipeline.time_database import ParseError, parse_labs

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture(scope="module")
def labs():
    page = (FIXTURES / "bipm_showlab.html").read_bytes().decode("utf-8")
    return {lab.code: lab for lab in parse_labs(page)}


def test_covers_every_lab_in_the_api_list(labs):
    api = parse_api_labs((FIXTURES / "bipm_labs.json").read_bytes())
    assert set(api) <= set(labs)


def test_current_lab_fields(labs):
    ptb = labs["PTB"]
    assert ptb.city == "Braunschweig"
    assert ptb.country == "Germany"
    assert ptb.year_stop is None
    assert ptb.year_start == 1968


def test_former_labs_have_a_stop_year(labs):
    assert labs["BOM"].year_stop == 2023
    assert labs["BOM"].city == "Skopje"
    assert labs["UTE"].city == "Montevideo"
    assert labs["IGNA"].year_stop == 2025


def test_new_lab_not_yet_in_circular_t(labs):
    assert labs["EE"].year_start == 2026
    assert labs["EE"].year_stop is None
    assert labs["EE"].city == "Tallinn"


def test_html_entities_and_accents_are_decoded(labs):
    assert labs["DFM"].city == "Hørsholm"
    assert labs["UME"].country == "Türkiye"
    assert "&" not in labs["BEV"].name


def test_page_without_table_is_rejected():
    with pytest.raises(ParseError):
        parse_labs("<html></html>")
