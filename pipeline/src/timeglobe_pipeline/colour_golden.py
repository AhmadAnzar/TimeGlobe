"""Golden values for the web app's drift colour scale (apps/web/src/colour).

    python -m timeglobe_pipeline.colour_golden [OUT_JSON]

Runs the approved Python scale (spike_coverage.symlog + matplotlib's PuOr, normalised over [-1, 1]) on a
fixed list of drifts and writes the position on the scale and the 8-bit colour for each. The web test
compares the TypeScript scale against this file, so a change to either side shows up as a failing test.
Needs the optional `spike` extra (matplotlib). Offline; writes one file.
"""

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import Normalize, to_hex  # noqa: E402

from timeglobe_pipeline.fetch import REPO_ROOT  # noqa: E402
from timeglobe_pipeline.spike_coverage import CLIP_NS, LINTHRESH_NS, symlog  # noqa: E402

DEFAULT_OUT = REPO_ROOT / "apps" / "web" / "src" / "colour" / "golden.json"

# Edges that matter: zero, either side of the linear threshold, the decades, the saturation point and beyond.
MAGNITUDES_NS = [0.1, 1, 2.5, 4.9, 5, 5.1, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 9999, 10000, 10001, 20000, 1e6]


def golden_rows() -> list[dict]:
    cmap = plt.get_cmap("PuOr")
    norm = Normalize(-1, 1)
    drifts = [0.0] + [s * m for m in MAGNITUDES_NS for s in (-1, 1)]
    rows = []
    for ns in sorted(drifts):
        position = float(symlog(ns))
        rows.append({"ns": ns, "position": position, "hex": to_hex(cmap(norm(position)))})
    return rows


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": "timeglobe_pipeline.spike_coverage.symlog + matplotlib PuOr, Normalize(-1, 1)",
        "matplotlib": matplotlib.__version__,
        "linthresh_ns": LINTHRESH_NS,
        "clip_ns": CLIP_NS,
        "rows": golden_rows(),
    }
    out.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(payload['rows'])} rows to {out}")


if __name__ == "__main__":
    main()
