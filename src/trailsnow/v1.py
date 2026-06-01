"""v1 entrypoint: trail geometry + nearest SNOTEL reading.

Usage:
    python -m trailsnow.v1 --seed skyline_loop_rainier
    python -m trailsnow.v1 --all
    python -m trailsnow.v1 --bbox 46.83,-121.78,46.86,-121.72 --name "Skyline Trail"
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path
from typing import Iterable

import yaml

from .overpass import fetch_trails_in_bbox
from .snotel import (
    Station,
    load_stations,
    nearest_active,
    nearest_stations,
    latest_snow,
)

SEEDS_PATH = Path("seeds/trails.yaml")


def _trail_centroid(coords: list[list[float]]) -> tuple[float, float]:
    lats = [c[0] for c in coords]
    lons = [c[1] for c in coords]
    return statistics.fmean(lats), statistics.fmean(lons)


def _trail_length_km(coords: list[list[float]]) -> float:
    from math import radians, sin, cos, asin, sqrt
    R = 6371.0
    total = 0.0
    for (a_lat, a_lon), (b_lat, b_lon) in zip(coords, coords[1:]):
        p1, p2 = radians(a_lat), radians(b_lat)
        dphi = radians(b_lat - a_lat)
        dlam = radians(b_lon - a_lon)
        h = sin(dphi / 2) ** 2 + cos(p1) * cos(p2) * sin(dlam / 2) ** 2
        total += 2 * R * asin(sqrt(h))
    return total


def _fmt_reading(snow: dict, code: str) -> str:
    r = snow.get(code, {})
    v = r.get("value")
    d = r.get("date")
    if v is None:
        return f"{code}: n/a"
    return f"{code}: {v} {r.get('unit', 'in')} (as of {d})"


def run_seed(seed: dict, stations: list[Station]) -> None:
    name = seed["name"]
    bbox = tuple(seed["bbox"])
    name_rx = seed.get("name_regex")
    expected = seed.get("expected", "")

    print(f"\n=== {name} ({seed['area']}) ===")
    print(f"    expected: {expected}")
    print(f"    bbox: {bbox}  name_regex: {name_rx!r}")

    try:
        trails = fetch_trails_in_bbox(bbox, name_regex=name_rx)
    except Exception as e:
        print(f"    [overpass error] {e}")
        return
    if not trails:
        print("    no matching trails found in bbox; widen bbox or relax name_regex")
        return

    # Aggregate: total length and a single centroid for the whole match group.
    all_coords = [pt for t in trails for pt in t["coords"]]
    total_km = sum(_trail_length_km(t["coords"]) for t in trails)
    clat, clon = _trail_centroid(all_coords)
    print(f"    matched ways: {len(trails)}  total length: {total_km:.2f} km")
    print(f"    centroid: ({clat:.5f}, {clon:.5f})")
    for t in trails[:5]:
        nm = t["name"] or "(unnamed)"
        km = _trail_length_km(t["coords"])
        print(f"      - way {t['id']}: {nm}  [{km:.2f} km]")
    if len(trails) > 5:
        print(f"      ... and {len(trails) - 5} more")

    hit = nearest_active(clat, clon, stations, k=5)
    if hit is None:
        print("    no nearby SNOTEL station returned recent data")
        # Still show the closest 3 for debugging.
        for dist, st in nearest_stations(clat, clon, stations, k=3):
            print(f"      candidate (no data): {st.name} ({st.triplet})  {dist:.1f} km")
        return
    st, dist_km, snow = hit
    elev = f"{st.elevation_ft:.0f} ft" if st.elevation_ft is not None else "elev n/a"
    print(
        f"    nearest active SNOTEL: {st.name} ({st.triplet})  "
        f"{dist_km:.1f} km away  {elev}"
    )
    print(f"      {_fmt_reading(snow, 'SNWD')}")
    print(f"      {_fmt_reading(snow, 'WTEQ')}")
    print("    estimated snow conditions: (v1, point-station only, not trail-elevation corrected)")


def load_seeds() -> list[dict]:
    return yaml.safe_load(SEEDS_PATH.read_text())["trails"]


def main(argv: Iterable[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="v1: trail geometry + nearest SNOTEL")
    p.add_argument("--seed", help="run a single seed by id")
    p.add_argument("--all", action="store_true", help="run all seeds")
    p.add_argument("--bbox", help="custom bbox: south,west,north,east")
    p.add_argument("--name", help="name regex for --bbox mode")
    args = p.parse_args(list(argv) if argv is not None else None)

    print("loading SNOTEL station catalog ...", end=" ", flush=True)
    stations = load_stations()
    print(f"{len(stations)} stations across {len({s.network for s in stations})} networks")

    if args.bbox:
        bbox = tuple(float(x) for x in args.bbox.split(","))
        seed = {
            "id": "custom",
            "name": args.name or "custom bbox",
            "area": "custom",
            "bbox": list(bbox),
            "name_regex": args.name,
            "expected": "",
        }
        run_seed(seed, stations)
        return 0

    seeds = load_seeds()
    if args.seed:
        match = [s for s in seeds if s["id"] == args.seed]
        if not match:
            print(f"no seed with id {args.seed!r}; available: {[s['id'] for s in seeds]}", file=sys.stderr)
            return 2
        run_seed(match[0], stations)
        return 0

    if args.all or (not args.seed and not args.bbox):
        for s in seeds:
            run_seed(s, stations)
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
