from datetime import timedelta

import httpx
import pytest

from timeglobe_pipeline.http import DisallowedURL, FetchError, PoliteClient

ALLOWED = ("https://example.test/api/",)
URL = "https://example.test/api/labs"


class Recorder:
    """Scripted transport: replays the given responses and records requests."""

    def __init__(self, *responses: httpx.Response) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.responses.pop(0)


def make_client(recorder: Recorder, sleeps: list[float], clock: list[float], **kwargs):
    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock[0] += seconds

    return PoliteClient(
        "TimeGlobe-test (+contact)",
        ALLOWED,
        transport=httpx.MockTransport(recorder),
        sleep=sleep,
        now=lambda: clock[0],
        **kwargs,
    )


def test_sends_user_agent():
    rec = Recorder(httpx.Response(200, content=b"ok"))
    client = make_client(rec, [], [0.0])
    assert client.get(URL) == b"ok"
    assert rec.requests[0].headers["User-Agent"] == "TimeGlobe-test (+contact)"


def test_refuses_url_outside_allowlist_without_requesting():
    rec = Recorder()
    client = make_client(rec, [], [0.0])
    with pytest.raises(DisallowedURL):
        client.get("https://example.test/ftp/raw/clock.dat")
    assert rec.requests == []


def test_does_not_follow_redirects():
    rec = Recorder(httpx.Response(302, headers={"Location": "https://example.test/ftp/raw"}))
    client = make_client(rec, [], [0.0])
    with pytest.raises(FetchError):
        client.get(URL)
    assert len(rec.requests) == 1


def test_retries_5xx_with_exponential_backoff_then_succeeds():
    rec = Recorder(httpx.Response(503), httpx.Response(500), httpx.Response(200, content=b"ok"))
    sleeps: list[float] = []
    client = make_client(rec, sleeps, [100.0], min_interval=0)
    assert client.get(URL) == b"ok"
    assert sleeps == [1.0, 2.0]


def test_honours_retry_after_on_429():
    rec = Recorder(
        httpx.Response(429, headers={"Retry-After": "30"}), httpx.Response(200, content=b"ok")
    )
    sleeps: list[float] = []
    client = make_client(rec, sleeps, [100.0], min_interval=0)
    client.get(URL)
    assert sleeps == [30.0]


def test_gives_up_after_max_retries():
    rec = Recorder(*[httpx.Response(503) for _ in range(3)])
    client = make_client(rec, [], [100.0], min_interval=0, max_retries=2)
    with pytest.raises(FetchError, match="giving up"):
        client.get(URL)
    assert len(rec.requests) == 3


def test_does_not_retry_client_errors():
    rec = Recorder(httpx.Response(404))
    client = make_client(rec, [], [100.0], min_interval=0)
    with pytest.raises(FetchError, match="404"):
        client.get(URL)
    assert len(rec.requests) == 1


def test_spaces_requests_by_min_interval():
    rec = Recorder(httpx.Response(200, content=b"a"), httpx.Response(200, content=b"b"))
    sleeps: list[float] = []
    client = make_client(rec, sleeps, [100.0], min_interval=5.0)
    client.get(URL, {"lab": "a"})
    client.get(URL, {"lab": "b"})
    assert sleeps == [5.0]


def test_cache_hit_skips_network(tmp_path):
    rec = Recorder(httpx.Response(200, content=b"first"))
    client = make_client(rec, [], [100.0], cache_dir=tmp_path)
    assert client.get(URL, {"lab": "a"}) == b"first"
    assert client.get(URL, {"lab": "a"}) == b"first"
    assert len(rec.requests) == 1


def test_cache_key_includes_params(tmp_path):
    rec = Recorder(httpx.Response(200, content=b"a"), httpx.Response(200, content=b"b"))
    client = make_client(rec, [], [100.0], cache_dir=tmp_path, min_interval=0)
    assert client.get(URL, {"lab": "a"}) == b"a"
    assert client.get(URL, {"lab": "b"}) == b"b"


def test_cache_expires_after_ttl(tmp_path):
    rec = Recorder(httpx.Response(200, content=b"old"), httpx.Response(200, content=b"new"))
    clock = [0.0]
    client = make_client(
        rec, [], clock, cache_dir=tmp_path, cache_ttl=timedelta(days=30), min_interval=0
    )
    client.get(URL)
    # Cache entry mtime is real wall-clock time, so move the fake clock far past it.
    clock[0] = 1e12
    assert client.get(URL) == b"new"


def test_failed_responses_are_not_cached(tmp_path):
    rec = Recorder(httpx.Response(404), httpx.Response(200, content=b"ok"))
    client = make_client(rec, [], [100.0], cache_dir=tmp_path, min_interval=0)
    with pytest.raises(FetchError):
        client.get(URL)
    assert client.get(URL) == b"ok"
