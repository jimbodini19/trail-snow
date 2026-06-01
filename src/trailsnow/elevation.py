"""USGS 3DEP elevation via the Elevation Point Query Service (EPQS).

EPQS is one-point-per-call and rate-limited, so we cache aggressively keyed
on lat/lon rounded to 5 decimal places (~1.1 m precision, well below 3DEP's
1-arcsec resolution).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests

EPQS_URL = "https://epqs.nationalmap.gov/v1/json"
USER_AGENT = "trail-snow/0.2 (https://example.local)"
CACHE_DIR = Path("data/cache/elevation")
SLEEP_BETWEEN_S = 0.15  # be polite


def _cache_path(lat: float, lon: float) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = f"{round(lat, 5)}_{round(lon, 5)}.json"
    return CACHE_DIR / key


def elevation_m(lat: float, lon: float, timeout: int = 30) -> float | None:
    """Return elevation in meters at (lat, lon), or None on failure."""
    cp = _cache_path(lat, lon)
    if cp.exists():
        try:
            return json.loads(cp.read_text()).get("elev_m")
        except (json.JSONDecodeError, KeyError):
            pass
    params = {"x": lon, "y": lat, "units": "Meters", "wkid": 4326}
    try:
        r = requests.get(EPQS_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=timeout)
        r.raise_for_status()
        v = r.json().get("value")
        elev = float(v) if v not in (None, "", "null") else None
    except (requests.RequestException, ValueError):
        elev = None
    cp.write_text(json.dumps({"elev_m": elev}))
    time.sleep(SLEEP_BETWEEN_S)
    return elev


def elevations_m(points: list[tuple[float, float]]) -> list[float | None]:
    return [elevation_m(lat, lon) for lat, lon in points]
