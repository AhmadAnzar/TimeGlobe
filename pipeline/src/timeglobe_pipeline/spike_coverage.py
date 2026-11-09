"""Phase 1 spike: per-lab coverage chart and drift colour-scale study.

    python -m timeglobe_pipeline.spike_coverage [SERIES_DIR]

Reads every *.json UTC-UTC(k) response in SERIES_DIR (default pipeline/out/raw/utc, falling back
to the saved fixtures) and writes into pipeline/out/: coverage.csv, coverage.png,
colour_scale.png and a stats printout used to choose the scale parameters.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import Normalize  # noqa: E402

from timeglobe_pipeline.bipm_api import Series, parse_series  # noqa: E402
from timeglobe_pipeline.fetch import REPO_ROOT  # noqa: E402

MJD_1998 = 50814
STEP = 5
EPOCH = date(1858, 11, 17)

# Approved colour scale: symmetric log, linear inside +-LINTHRESH, saturated beyond CLIP.
# Point styling: every filled point gets a thin dark outline so near-zero (pale) values stay
# visible; "no data" is a hollow dashed ring, never a fill.
LINTHRESH_NS = 5.0
CLIP_NS = 10000.0


def mjd_date(mjd: int) -> date:
    return EPOCH + timedelta(days=mjd)


def symlog(value_ns, linthresh: float = LINTHRESH_NS, clip: float = CLIP_NS):
    """Map ns to [-1, 1]: sign * log10(1 + |v|/linthresh), scaled so |v| = clip gives +-1."""
    v = np.asarray(value_ns, dtype=float)
    scaled = np.log10(1 + np.abs(v) / linthresh) / np.log10(1 + clip / linthresh)
    return np.clip(np.sign(v) * scaled, -1, 1)


def load_all(series_dir: Path) -> dict[str, Series]:
    files = sorted(series_dir.glob("*.json")) if series_dir.is_dir() else []
    if not files:
        series_dir = REPO_ROOT / "tests" / "fixtures"
        files = sorted(series_dir.glob("bipm_utc_*.json"))
        print(f"no series in the default folder; using fixtures in {series_dir}")
    out = {}
    for path in files:
        (series,) = parse_series(path.read_bytes())
        out[series.name.removeprefix("UTC-UTC(").removesuffix(")")] = series
    return out


def coverage_rows(all_series: dict[str, Series], last_mjd: int) -> list[dict]:
    rows = []
    for lab, s in sorted(all_series.items()):
        span_steps = (s.mjd[-1] - s.mjd[0]) // STEP + 1
        expected_since_1998 = (last_mjd - MJD_1998) // STEP + 1
        rows.append(
            {
                "lab": lab,
                "first": mjd_date(s.mjd[0]).isoformat(),
                "last": mjd_date(s.mjd[-1]).isoformat(),
                "n": len(s.mjd),
                "pct_of_own_span": round(100 * len(s.mjd) / span_steps, 1),
                "pct_since_1998": round(100 * len(s.mjd) / expected_since_1998, 1),
                "n_with_uncertainty": sum(u is not None for u in s.unc_ns),
            }
        )
    return rows


def plot_coverage(all_series: dict[str, Series], last_mjd: int, path: Path) -> None:
    bins = (last_mjd - MJD_1998) // STEP + 1
    order = sorted(all_series, key=lambda lab: (all_series[lab].mjd[0], lab))
    grid = np.zeros((len(order), bins))
    for row, lab in enumerate(order):
        s = all_series[lab]
        for mjd, unc in zip(s.mjd, s.unc_ns):
            col = (mjd - MJD_1998) // STEP
            if 0 <= col < bins:
                grid[row, col] = 2 if unc is not None else 1
    fig, ax = plt.subplots(figsize=(12, max(3, 0.13 * len(order))))
    cmap = plt.matplotlib.colors.ListedColormap(["#ffffff", "#9ecae1", "#08519c"])
    ax.imshow(grid, aspect="auto", cmap=cmap, interpolation="nearest", vmin=0, vmax=2,
              extent=(1998.0, 1998.0 + bins * STEP / 365.25, len(order), 0))
    ax.set_yticks(np.arange(len(order)) + 0.5, order, fontsize=5)
    ax.set_xlabel("year")
    ax.set_title("UTC-UTC(k) values per lab: light = value only, dark = value + uncertainty, white = gap")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_scale(all_series: dict[str, Series], latest: dict[str, float], path: Path) -> None:
    values = np.concatenate([np.array(s.value_ns) for s in all_series.values()])
    cmap = plt.get_cmap("PuOr")  # purple-orange diverging: safe for the common colour-vision types
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7), height_ratios=[3, 2])
    edges = np.linspace(-1, 1, 81)
    ax1.hist(symlog(values), bins=edges, color="#555555")
    for e, c in zip(edges[:-1], edges[1:]):
        ax1.axvspan(e, c, ymin=0, ymax=0.04, color=cmap(Normalize(-1, 1)((e + c) / 2)))
    ticks_ns = [-10000, -1000, -100, -10, 0, 10, 100, 1000, 10000]
    ax1.set_xticks(symlog(ticks_ns), [f"{t:+d}" if t else "0" for t in ticks_ns])
    ax1.set_yscale("log")
    ax1.set_xlabel(f"UTC-UTC(k) in ns (symlog: linear within +-{LINTHRESH_NS:g} ns, saturated beyond +-{CLIP_NS:g})")
    ax1.set_title(f"All {len(values):,} values on the approved scale; bar = colour")
    labs = sorted(latest, key=lambda lab: latest[lab])
    ax2.bar(range(len(labs)), np.ones(len(labs)),
            color=[cmap(Normalize(-1, 1)(symlog(latest[lab]))) for lab in labs],
            edgecolor="#333333", linewidth=0.6)
    ax2.scatter([len(labs) + 2], [0.5], s=260, facecolors="none", edgecolors="#333333",
                linestyle=(0, (3, 2)), linewidth=1.2, clip_on=False)
    ax2.annotate("no data", (len(labs) + 2, 0.05), ha="center", fontsize=7)
    ax2.set_xticks(range(len(labs)), labs, rotation=90, fontsize=5)
    ax2.set_yticks([])
    ax2.set_title("Latest value of each lab with data, sorted, on the scale")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def print_scale_stats(all_series: dict[str, Series]) -> None:
    values = np.abs(np.concatenate([np.array(s.value_ns) for s in all_series.values()]))
    pct = {p: float(np.percentile(values, p)) for p in (50, 75, 90, 95, 99)}
    print("|value| percentiles (ns):", {p: round(v, 1) for p, v in pct.items()}, "max", round(values.max()))
    for lin, clip in [(1, 100), (1, 1000), (1, 10000), (5, 1000), (10, 1000)]:
        saturated = float(np.mean(values >= clip)) * 100
        linear = float(np.mean(values <= lin)) * 100
        print(f"  linthresh {lin:>3} ns, clip {clip:>6} ns: {linear:4.1f}% in the linear zone, {saturated:4.1f}% saturated")


def main(argv: list[str]) -> int:
    series_dir = Path(argv[0]) if argv else REPO_ROOT / "pipeline" / "out" / "raw" / "utc"
    all_series = load_all(series_dir)
    last_mjd = max(s.mjd[-1] for s in all_series.values())
    out = REPO_ROOT / "pipeline" / "out"
    out.mkdir(parents=True, exist_ok=True)

    rows = coverage_rows(all_series, last_mjd)
    with (out / "coverage.csv").open("w", encoding="utf-8", newline="") as f:
        f.write(",".join(rows[0]) + "\n")
        for row in rows:
            f.write(",".join(str(v) for v in row.values()) + "\n")
    total = sum(r["n"] for r in rows)
    print(f"{len(rows)} labs, {total:,} values, latest date {mjd_date(last_mjd)}; "
          f"labs with <50% of their own span filled: {[r['lab'] for r in rows if r['pct_of_own_span'] < 50]}")

    latest = {lab: s.value_ns[-1] for lab, s in all_series.items() if s.mjd[-1] == last_mjd}
    plot_coverage(all_series, last_mjd, out / "coverage.png")
    plot_scale(all_series, latest, out / "colour_scale.png")
    print_scale_stats(all_series)
    print(f"wrote {out / 'coverage.csv'}, coverage.png, colour_scale.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
