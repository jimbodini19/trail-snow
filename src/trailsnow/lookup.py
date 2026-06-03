"""Look up a trail by name, then run v2 analysis on it.

Two stages:
  1. Geocode the name via OSM Nominatim, constrained to ID/WA/OR/MT.
  2. Take the bounding box of the matched feature, run analyze_seed.

Usage:
    python -m trailsnow.lookup "Goat Lake Trail"
    python -m trailsnow.lookup "Snow Lake" --state WA
    python -m trailsnow.lookup "Iron Goat Trail" --report out/lookup.html
    python -m trailsnow.lookup "Mailbox Peak" --add-to-seeds
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import requests
import yaml

from .snodas import load_depth
from .v2 import analyze_seed, print_result, DEFAULT_SPACING_M, DEFAULT_THRESHOLD_CM

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "trail-snow/0.3 (contact: jimmy@guidedgrowthmktg.com)"
SEEDS_PATH = Path("seeds/trails.yaml")

STATE_BOUNDS = {
    "WA": (45.54, -124.84, 49.00, -116.92),
    "OR": (41.99, -124.57, 46.29, -116.46),
    "ID": (42.00, -117.24, 49.00, -111.04),
    "MT": (44.36, -116.05, 49.00, -104.04),
}


def _nominatim(query: str, state: str | None = None, limit: int = 5) -> list[dict]:
    params = {
        "q": query,
        "format": "json",
        "limit": str(limit),
        "addressdetails": "1",
        "extratags": "1",
        "namedetails": "1",
    }
    if state and state in STATE_BOUNDS:
        s, w, n, e = STATE_BOUNDS[state]
        params["viewbox"] = f"{w},{n},{e},{s}"
        params["bounded"] = "1"
    r = requests.get(NOMINATIM_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=30)
    r.raise_for_status()
    return r.json()


def _bbox_of(hit: dict, pad_deg: float = 0.005) -> tuple[float, float, float, float]:
    """Return (south, west, north, east) with a small pad for very-short matches."""
    bb = hit.get("boundingbox")
    if bb and len(bb) == 4:
        s, n, w, e = float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3])
    else:
        lat = float(hit["lat"])
        lon = float(hit["lon"])
        s, n, w, e = lat - 0.01, lat + 0.01, lon - 0.01, lon + 0.01
    if (n - s) < 0.005:
        s -= pad_deg
        n += pad_deg
    if (e - w) < 0.005:
        w -= pad_deg
        e += pad_deg
    return s, w, n, e


def _suggest_regex(query: str) -> str:
    """Build a tolerant name regex from a free-text query."""
    words = [w for w in re.findall(r"[A-Za-z0-9]+", query) if w.lower() not in {"the", "trail", "loop", "to"}]
    if not words:
        return query
    if len(words) == 1:
        return words[0]
    return "|".join(words[:3])


def _format_hit(i: int, hit: dict) -> str:
    name = hit.get("display_name", "?")
    typ = hit.get("type", "?")
    cls = hit.get("class", "?")
    bb = hit.get("boundingbox")
    bbstr = f"bbox=[{float(bb[0]):.4f},{float(bb[2]):.4f},{float(bb[1]):.4f},{float(bb[3]):.4f}]" if bb else ""
    return f"  [{i}] {cls}/{typ}  {name}\n      {bbstr}"


def _yaml_quote(value) -> str:
    """Double-quoted YAML scalar that is safe for any single-line string.

    A trail name like "Trail: The Sequel" written as a bare scalar re-parses as
    a mapping and breaks every later yaml.safe_load of seeds/trails.yaml.
    Double-quoted style only needs backslash and double-quote escaped.
    """
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _seed_id_exists(seed_id: str) -> bool:
    """True if seeds/trails.yaml already lists a trail with this id."""
    if not SEEDS_PATH.exists():
        return False
    try:
        doc = yaml.safe_load(SEEDS_PATH.read_text()) or {}
    except yaml.YAMLError:
        return False
    return any((t or {}).get("id") == seed_id for t in doc.get("trails", []))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Look up a trail by name and run v2.")
    p.add_argument("query", help="Trail name to search for")
    p.add_argument("--state", choices=list(STATE_BOUNDS.keys()),
                   help="Bias search to this state's bbox")
    p.add_argument("--pick", type=int, default=1,
                   help="Which Nominatim hit to use (1-indexed). Default 1.")
    p.add_argument("--report", help="Render the result to this HTML report path (overwrites)")
    p.add_argument("--threshold-cm", type=float, default=DEFAULT_THRESHOLD_CM)
    p.add_argument("--spacing-m", type=float, default=DEFAULT_SPACING_M)
    p.add_argument("--add-to-seeds", action="store_true",
                   help="Append the resolved trail to seeds/trails.yaml so it shows up in --all runs")
    args = p.parse_args(argv)

    print(f"Searching OSM for: {args.query!r}" + (f" in {args.state}" if args.state else ""))
    hits = _nominatim(args.query, state=args.state, limit=5)
    if not hits:
        print("No Nominatim hits. Try different wording or pass --state.", file=sys.stderr)
        return 1

    print(f"Top {len(hits)} hits:")
    for i, h in enumerate(hits, 1):
        print(_format_hit(i, h))

    pick = max(1, min(args.pick, len(hits)))
    chosen = hits[pick - 1]
    s, w, n, e = _bbox_of(chosen)
    print(f"\nUsing hit {pick}: {chosen.get('display_name','?')}")
    print(f"  bbox: ({s:.4f}, {w:.4f}, {n:.4f}, {e:.4f})")

    name_rx = _suggest_regex(args.query)
    print(f"  name regex: {name_rx!r}")

    print("\nLoading latest SNODAS daily grid ...", end=" ", flush=True)
    grid, grid_date = load_depth()
    print(f"using {grid_date}")

    seed = {
        "id": "lookup_" + re.sub(r"[^a-z0-9]+", "_", args.query.lower()).strip("_"),
        "name": args.query,
        "area": (args.state or "lookup") + " - via Nominatim",
        "bbox": [s, w, n, e],
        "name_regex": name_rx,
        "expected": "",
    }
    result = analyze_seed(seed, grid, grid_date, args.spacing_m, args.threshold_cm)
    print_result(result)

    if args.add_to_seeds and result["ok"]:
        if _seed_id_exists(seed["id"]):
            print(f"\nseed id {seed['id']!r} already in {SEEDS_PATH}; not appending again")
        else:
            with SEEDS_PATH.open("a") as fh:
                fh.write(
                    f"\n  - id: {_yaml_quote(seed['id'])}\n"
                    f"    name: {_yaml_quote(seed['name'])}\n"
                    f"    area: {_yaml_quote(seed['area'])}\n"
                    f"    bbox: [{s}, {w}, {n}, {e}]\n"
                    f"    name_regex: {_yaml_quote(name_rx)}\n"
                    f"    expected: lookup\n"
                )
            print(f"\nappended to {SEEDS_PATH}")

    if args.report:
        from .report import render_v2_report
        out = Path(args.report)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_v2_report([result]))
        print(f"report written: {out}")

    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
