"""HTTP client that follows the project's scraping rules.

- Only URLs under an allowed prefix are fetched.
- Every request carries an honest User-Agent naming the project.
- Requests are spaced by min_interval; 429/5xx/transport errors back off exponentially
  (honouring Retry-After) and give up after max_retries.
- Successful responses are cached on disk, so re-running never refetches while the
  entry is younger than cache_ttl. Use a ttl of 30 days for scrapers ("at most monthly").
"""

import hashlib
import json
import time
from collections.abc import Callable, Mapping
from datetime import timedelta
from pathlib import Path

import httpx


class FetchError(Exception):
    pass


class DisallowedURL(FetchError):
    pass


class PoliteClient:
    def __init__(
        self,
        user_agent: str,
        allowed_prefixes: tuple[str, ...],
        *,
        forbidden_prefixes: tuple[str, ...] = (),
        monthly_prefixes: tuple[str, ...] = (),
        monthly_days: int = 30,
        cache_dir: Path | None = None,
        cache_ttl: timedelta | None = None,
        min_interval: float = 2.0,
        max_retries: int = 4,
        backoff_base: float = 2.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._allowed = allowed_prefixes
        self._forbidden = forbidden_prefixes
        self._monthly = monthly_prefixes
        self._monthly_ttl = timedelta(days=monthly_days)
        self._cache_dir = cache_dir
        self._ttl = cache_ttl
        self._min_interval = min_interval
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._sleep = sleep
        self._now = now
        self._last_request: float | None = None
        self._http = httpx.Client(
            headers={"User-Agent": user_agent},
            transport=transport,
            timeout=30.0,
            follow_redirects=False,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "PoliteClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def get(self, url: str, params: Mapping[str, str] | None = None) -> bytes:
        self._check_allowed(url)

        cached = self._read_cache(url, params)
        if cached is not None:
            return cached

        for attempt in range(self._max_retries + 1):
            self._respect_interval()
            try:
                response = self._http.get(url, params=params)
            except httpx.TransportError as exc:
                failure: str = repr(exc)
                retry_after = None
            else:
                if response.status_code == 200:
                    self._write_cache(url, params, response.content)
                    return response.content
                if response.status_code != 429 and response.status_code < 500:
                    raise FetchError(f"{response.status_code} for {url}")
                failure = f"HTTP {response.status_code}"
                retry_after = _retry_after_seconds(response)
            if attempt == self._max_retries:
                raise FetchError(f"giving up on {url} after {attempt + 1} attempts: {failure}")
            self._sleep(retry_after if retry_after is not None else self._backoff_base**attempt)
        raise AssertionError("unreachable")

    def _check_allowed(self, url: str) -> None:
        # Dot segments could climb out of an allowed prefix into a forbidden folder.
        if "/../" in url or url.endswith("/..") or "%2e" in url.lower():
            raise DisallowedURL(f"path traversal not permitted: {url}")
        if url.startswith(self._forbidden):
            raise DisallowedURL(f"forbidden source: {url}")
        if not url.startswith(self._allowed):
            raise DisallowedURL(f"not an allowed source: {url}")

    def _ttl_for(self, url: str) -> timedelta | None:
        """Scraped pages are served from a saved copy for the whole monthly window, whatever the
        default cache lifetime is; everything else uses the client's own lifetime."""
        return self._monthly_ttl if url.startswith(self._monthly) else self._ttl

    def _respect_interval(self) -> None:
        if self._last_request is not None:
            wait = self._min_interval - (self._now() - self._last_request)
            if wait > 0:
                self._sleep(wait)
        self._last_request = self._now()

    def _cache_path(self, url: str, params: Mapping[str, str] | None) -> Path | None:
        if self._cache_dir is None:
            return None
        key = json.dumps([url, sorted((params or {}).items())])
        return self._cache_dir / hashlib.sha256(key.encode()).hexdigest()

    def _read_cache(self, url: str, params: Mapping[str, str] | None) -> bytes | None:
        path = self._cache_path(url, params)
        if path is None or not path.is_file():
            return None
        ttl = self._ttl_for(url)
        if ttl is not None and self._now() - path.stat().st_mtime > ttl.total_seconds():
            return None
        return path.read_bytes()

    def _write_cache(self, url: str, params: Mapping[str, str] | None, body: bytes) -> None:
        path = self._cache_path(url, params)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)


def _retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None
