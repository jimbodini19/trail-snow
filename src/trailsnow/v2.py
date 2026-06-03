"""v2 entrypoint: SNODAS-sampled snowed-in fraction per trail.

For each seed trail:
  1. Pull OSM geometry via Overpass (cached).
  2. Densify the line to one sample every ~300 m.
  3. Sample SNODAS snow depth at each point from the latest available daily grid.
  4. Sample USGS 3DEP elevation at each point.
  5. Compute the snowed-in fraction (samples with depth >= threshold).

Default threshold: 10 cm (4 in) of snow depth, locked in with Jimmy.

Usage:
    python -m trailsnow.v2 --all
    python -m trailsnow.v2 --seed skyline_loop_rainier --threshold-cm 15
    python -m trailsnow.v2 --all --report out/v2.html
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path
from typing import Iterable

import yaml

from .geom import cumulative_distances_m, line_length_m, sample_along
from .overpass import fetch_trails_in_bbox
from .snodas import depths_along, load_depth
from .elevation import elevations_m
from .roads import query_road_status

SEEDS_PATH = Path("seeds/trails.yaml")
DEFAULT_SPACING_M = 300.0
DEFAULT_THRESHOLD_CM = 10.0


def _mm_to_cm(mm: float | None) -> float | None:
    return None if mm is None else mm / 10.0


def _summarize_elevs(elevs: list[float | None]) -> tuple[float | None, float | None, float | None]:
    vals = [e for e in elevs if e is not None]
    if not vals:
        return None, None, None
    return min(vals), statistics.median(vals), max(vals)


def analyze_seed(
    seed: dict,
    grid,
    grid_date,
    spacing_m: float,
    threshold_cm: float,
) -> dict:
    bbox = tuple(seed["bbox"])
    name_rx = seed.get("name_regex")
    try:
        trails = fetch_trails_in_bbox(bbox, name_regex=name_rx)
    except Exception as e:
        # One Overpass failure must not abort an entire --all run. Degrade this
        # seed to a no-data result; the report and print_result handle not-ok.
        return {"seed": seed, "ok": False, "reason": f"overpass error: {e}"}
    if not trails:
        return {"seed": seed, "ok": False, "reason": "no OSM ways matched"}

    # Combine all matched ways into one ordered sample list per way, then aggregate.
    per_way = []
    all_samples: list[tuple[float, float]] = []
    for t in trails:
        coords = t["coords"]
        samples = sample_along(coords, spacing_m=spacing_m)
        per_way.append({"trail": t, "samples": samples,
                        "cum_m": cumulative_distances_m(samples),
                        "length_m": line_length_m(coords)})
        all_samples.extend(samples)

    depths_mm = depths_along(grid, all_samples)
    elevs = elevations_m(all_samples)

    # Snowed-in fraction (None samples excluded from the denominator).
    threshold_mm = threshold_cm * 10.0
    valid_depths = [d for d in depths_mm if d is not None]
    snowy_count = sum(1 for d in valid_depths if d >= threshold_mm)
    fraction = (snowy_count / len(valid_depths)) if valid_depths else None

    min_elev, med_elev, max_elev = _summarize_elevs(elevs)
    valid_depth_cm = [d / 10.0 for d in valid_depths]
    depth_stats = None
    if valid_depth_cm:
        depth_stats = {
            "min_cm": min(valid_depth_cm),
            "median_cm": statistics.median(valid_depth_cm),
            "max_cm": max(valid_depth_cm),
        }

    # Trailhead heuristic: the sample point with the lowest 3DEP elevation is
    # almost always at or very near the trailhead (or the parking lot end of a
    # spur). If SNODAS shows snow there, the access road probably got snow too.
    trailhead = None
    sample_pairs = list(zip(all_samples, depths_mm, elevs))
    elev_pairs = [(i, e) for i, (_, _, e) in enumerate(sample_pairs) if e is not None]
    if elev_pairs:
        th_idx = min(elev_pairs, key=lambda t: t[1])[0]
        th_pt, th_depth_mm, th_elev_m = sample_pairs[th_idx]
        trailhead = {
            "lat": th_pt[0],
            "lon": th_pt[1],
            "elevation_m": th_elev_m,
            "depth_cm": (th_depth_mm / 10.0) if th_depth_mm is not None else None,
        }
        # v3 pass 2: real FS road status near the trailhead. Two-call ArcGIS
        # spatial query, cached on disk by rounded lat/lon.
        try:
            road_status = query_road_status(th_pt[0], th_pt[1])
            trailhead["road_status"] = {
                "open": road_status["open"].__dict__ if road_status["open"] else None,
                "closed": road_status["closed"].__dict__ if road_status["closed"] else None,
            }
        except Exception as e:
            trailhead["road_status"] = {"error": str(e)}

    return {
        "seed": seed,
        "ok": True,
        "grid_date": grid_date.isoformat(),
        "spacing_m": spacing_m,
        "threshold_cm": threshold_cm,
        "n_samples_total": len(all_samples),
        "n_samples_valid": len(valid_depths),
        "snowed_in_fraction": fraction,
        "depth_stats": depth_stats,
        "elev_min_m": min_elev,
        "elev_median_m": med_elev,
        "elev_max_m": max_elev,
        "total_length_m": sum(w["length_m"] for w in per_way),
        "n_ways": len(trails),
        "samples": all_samples,
        "depths_mm": depths_mm,
        "elevs_m": elevs,
        "trailhead": trailhead,
    }


def print_result(res: dict) -> None:
    seed = res["seed"]
    print(f"\n=== {seed['name']} ({seed['area']}) ===")
    if not res["ok"]:
        print(f"    skipped: {res['reason']}")
        return
    frac = res["snowed_in_fraction"]
    frac_str = "n/a" if frac is None else f"{frac * 100:.0f}%"
    ds = res["depth_stats"]
    depth_str = (
        f"depth (cm): min={ds['min_cm']:.0f}, median={ds['median_cm']:.0f}, max={ds['max_cm']:.0f}"
        if ds else "depth: n/a"
    )
    elev_str = (
        f"elevation (m): min={res['elev_min_m']:.0f}, median={res['elev_median_m']:.0f}, max={res['elev_max_m']:.0f}"
        if res["elev_min_m"] is not None else "elevation: n/a"
    )
    print(f"    SNODAS day: {res['grid_date']}  threshold: {res['threshold_cm']:.0f} cm")
    print(f"    matched ways: {res['n_ways']}  total length: {res['total_length_m']/1000:.2f} km  samples: {res['n_samples_total']}")
    print(f"    snowed-in fraction: {frac_str}")
    print(f"    {depth_str}")
    print(f"    {elev_str}")


def load_seeds() -> list[dict]:
    return yaml.safe_load(SEEDS_PATH.read_text())["trails"]


def main(argv: Iterable[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="v2: SNODAS-sampled snowed-in fraction along trails")
    p.add_argument("--seed", help="run a single seed by id")
    p.add_argument("--all", action="store_true", help="run all seeds")
    p.add_argument("--bbox", help="custom bbox: south,west,north,east")
    p.add_argument("--name", help="name regex for --bbox mode")
    p.add_argument("--spacing-m", type=float, default=DEFAULT_SPACING_M)
    p.add_argument("--threshold-cm", type=float, default=DEFAULT_THRESHOLD_CM)
    p.add_argument("--report", dest="report_path", help="write HTML report to this path")
    args = p.parse_args(list(argv) if argv is not None else None)

    print("loading latest SNODAS daily grid ...", end=" ", flush=True)
    grid, grid_date = load_depth()
    print(f"using {grid_date}")

    if args.bbox:
        seed = {
            "id": "custom",
            "name": args.name or "custom bbox",
            "area": "custom",
            "bbox": [float(x) for x in args.bbox.split(",")],
            "name_regex": args.name,
            "expected": "",
        }
        results = [analyze_seed(seed, grid, grid_date, args.spacing_m, args.threshold_cm)]
    else:
        seeds = load_seeds()
        if args.seed:
            match = [s for s in seeds if s["id"] == args.seed]
            if not match:
                print(f"no seed with id {args.seed!r}", file=sys.stderr)
                return 2
            target_seeds = match
        else:
            target_seeds = seeds
        results = [analyze_seed(s, grid, grid_date, args.spacing_m, args.threshold_cm)
                   for s in target_seeds]

    for r in results:
        print_result(r)

    if args.report_path:
        from .report import render_v2_report
        out = Path(args.report_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_v2_report(results))
        print(f"\nreport written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
