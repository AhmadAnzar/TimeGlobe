"""Fetch one allowed URL and save the body: python -m timeglobe_pipeline.fetch URL OUT [key=value ...]

Goes through PoliteClient, so the allowlist, rate limit, backoff and disk cache all apply.
"""

import sys
from pathlib import Path

import httpx

from timeglobe_pipeline import config
from timeglobe_pipeline.http import FetchError, PoliteClient

REPO_ROOT = Path(__file__).resolve().parents[3]


def make_client(transport: httpx.BaseTransport | None = None) -> PoliteClient:
    config.load_env(REPO_ROOT / ".env")
    return PoliteClient(
        config.user_agent(),
        config.ALLOWED_PREFIXES,
        forbidden_prefixes=config.FORBIDDEN_PREFIXES,
        cache_dir=REPO_ROOT / "pipeline" / ".cache",
        transport=transport,
    )


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    url, out, *pairs = argv
    params = dict(pair.split("=", 1) for pair in pairs) or None
    with make_client() as client:
        try:
            body = client.get(url, params)
        except FetchError as exc:
            print(f"refused or failed: {exc}", file=sys.stderr)
            return 1
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    print(f"saved {len(body)} bytes to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
