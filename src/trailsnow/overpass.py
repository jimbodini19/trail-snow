"""Pull trail geometry from the Overpass API.

v1 takes a bounding box plus an optional name regex and returns the matching
ways with their node coordinates resolved. Results are cached on disk so
re-runs do not re-hit Overpass.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Iterable

import requests

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "trail-snow/0.1 (https://example.local)"
CACHE_DIR = Path("data/cache/overpass")


def _cache_key(query: str) -> Path:
    h = hashlib.sha1(query.encode("utf-8")).hexdigest()[:16]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{h}.json"


def _query_overpass(query: str, timeout: int = 60, max_attempts: int = 3) -> dict:
    cache = _cache_key(query)
    if cache.exists():
        return json.loads(cache.read_text())

    last_err: Exception | None = None
    for attempt in range(max_attempts):
        try:
            r = requests.post(
                OVERPASS_URL,
                data={"data": query},
                headers={"User-Agent": USER_AGENT},
                timeout=timeout,
            )
            if r.status_code == 200:
                cache.write_text(r.text)
                return r.json()
            if r.status_code in (429, 504):
                time.sleep(2 ** attempt * 5)
                continue
            r.raise_for_status()
        except requests.RequestException as e:
            last_err = e
            time.sleep(2 ** attempt * 2)
    raise RuntimeError(f"Overpass query failed after {max_attempts} attempts: {last_err}")


def fetch_trails_in_bbox(
    bbox: tuple[float, float, float, float],
    name_regex: str | None = None,
    highway_types: Iterable[str] = ("path", "footway", "track"),
) -> list[dict]:
    """Return a list of trail ways with resolved node coordinates.

    bbox: (south, west, north, east)
    Each returned dict has: id, name (or None), tags, coords (list of [lat, lon]).
    """
    s, w, n, e = bbox
    hw = "|".join(highway_types)
    name_clause = f'[name~"{name_regex}"]' if name_regex else ""
    # geom output gives us inline node coords so we do not need a second pass.
    q = (
        f'[out:json][timeout:60];'
        f'way({s},{w},{n},{e})["highway"~"{hw}"]{name_clause};'
        f'out geom;'
    )
    data = _query_overpass(q)
    trails: list[dict] = []
    for el in data.get("elements", []):
        if el.get("type") != "way":
            continue
        coords = [[pt["lat"], pt["lon"]] for pt in el.get("geometry", [])]
        if len(coords) < 2:
            continue
        tags = el.get("tags", {})
        trails.append(
            {
                "id": el["id"],
                "name": tags.get("name"),
                "tags": tags,
                "coords": coords,
            }
        )
    return trails
