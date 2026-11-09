import httpx
import pytest

from timeglobe_pipeline import fetch


@pytest.fixture
def requests_seen(monkeypatch, tmp_path):
    """Route fetch.main through a transport that records any request that would reach the network."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=b"data")

    monkeypatch.setenv("TIMEGLOBE_CONTACT", "test@example.test")
    monkeypatch.setattr(fetch, "REPO_ROOT", tmp_path)  # keep the test's cache out of the repo
    real_make_client = fetch.make_client
    monkeypatch.setattr(
        fetch, "make_client", lambda: real_make_client(transport=httpx.MockTransport(handler))
    )
    return seen


@pytest.mark.parametrize(
    "url",
    [
        "https://webtai.bipm.org/ftp/pub/tai/data/aos/clock.dat",
        "https://webtai.bipm.org/ftp/pub/tai/data/",
        "https://webtai.bipm.org/ftp/pub/tai/Circular-T/cirt/../../data/x",
        "https://webtai.bipm.org/ftp/pub/tai/other-products/notes/x.pdf",
        "https://example.com/anything",
        "https://webtai.bipm.org.evil.test/api/v1.0/get-data.html",
        "http://webtai.bipm.org/api/v1.0/get-data.html",
    ],
)
def test_fetch_refuses_forbidden_and_non_allowlisted_urls(url, requests_seen, tmp_path, capsys):
    out = tmp_path / "out.bin"
    assert fetch.main([url, str(out)]) == 1
    assert requests_seen == []  # nothing was sent
    assert not out.exists()
    assert "refused" in capsys.readouterr().err


def test_fetch_saves_an_allowed_url(requests_seen, tmp_path):
    out = tmp_path / "cirt.465"
    url = "https://webtai.bipm.org/ftp/pub/tai/Circular-T/cirt/cirt.465"
    assert fetch.main([url, str(out)]) == 0
    assert out.read_bytes() == b"data"
    assert len(requests_seen) == 1
