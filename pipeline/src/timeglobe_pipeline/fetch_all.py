"""Fetch UTC-UTC(k) for every lab in the API list: python -m timeglobe_pipeline.fetch_all [OUT_DIR]

One request per lab through PoliteClient (rate limited, cached). A lab that still fails after
the client's retries is reported at the end and does not stop the run.
"""

import sys
from pathlib import Path

from timeglobe_pipeline import bipm_api
from timeglobe_pipeline.fetch import REPO_ROOT, make_client
from timeglobe_pipeline.http import FetchError


def main(argv: list[str]) -> int:
    out_dir = Path(argv[0]) if argv else REPO_ROOT / "pipeline" / "out" / "raw" / "utc"
    out_dir.mkdir(parents=True, exist_ok=True)
    failed: list[str] = []
    with make_client() as client:
        labs = bipm_api.fetch_labs(client)
        for i, lab in enumerate(labs, 1):
            try:
                body = client.get(
                    bipm_api.API_URL, {"scale": "utc", "lab": lab.lower(), "outfile": "json"}
                )
                (series,) = bipm_api.parse_series(body)  # reject error payloads before saving
            except (FetchError, bipm_api.ApiError) as exc:
                failed.append(f"{lab}: {exc}")
                print(f"[{i}/{len(labs)}] {lab} FAILED")
                continue
            (out_dir / f"{lab}.json").write_bytes(body)
            note = f", {len(series.unc_unparsed)} junk uncertainty entries" if series.unc_unparsed else ""
            print(f"[{i}/{len(labs)}] {lab} {len(body)} bytes{note}")
    if failed:
        print("failed:\n  " + "\n  ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
