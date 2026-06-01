"""NRCS AWDB REST API client for SNOTEL station metadata and current readings.

Two functions matter for v1:
  - load_stations(): the full SNOTEL/SCAN/etc station list (cached on disk).
  - nearest_active(lat, lon): the closest SNOTEL station that reported snow
    within the last few days.
  - latest_snow(triplet): most recent WTEQ (snow water equivalent, in inches)
    and SNWD (snow depth, in inches) values within the last 7 days.

The AWDB stations endpoint filters did not behave as documented in early
testing, so we fetch all stations once and filter client-side. The full list
is ~5-10 MB and very cacheable.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

import requests

AWDB_BASE = "https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1"
USER_AGENT = "trail-snow/0.1 (https://example.local)"
CACHE_DIR = Path("data/cache")
STATIONS_CACHE = CACHE_DIR / "snotel_stations.json"
STATIONS_TTL_DAYS = 30

# Networks that carry useful snow data. SNTL = SNOTEL automated, SNTLT =
# SNOTEL light, SCAN = soil climate (some have snow), SNOW = manual snow course.
SNOW_NETWORKS = {"SNTL", "SNTLT", "SCAN", "SNOW"}


@dataclass
class Station:
    triplet: str
    station_id: str
    state: str
    network: str
    name: str
    lat: float
    lon: float
    elevation_ft: float | None

    @classmethod
    def from_api(cls, obj: dict) -> "Station":
        return cls(
            triplet=obj["stationTriplet"],
            station_id=obj.get("stationId", ""),
            state=obj.get("stateCode", ""),
            network=obj.get("networkCode", ""),
            name=obj.get("name", ""),
            lat=float(obj["latitude"]),
            lon=float(obj["longitude"]),
            elevation_ft=(
                float(obj["elevation"]) if obj.get("elevation") is not None else None
            ),
        )


def _stations_cache_fresh() -> bool:
    if not STATIONS_CACHE.exists():
        return False
    age = time.time() - STATIONS_CACHE.stat().st_mtime
    return age < STATIONS_TTL_DAYS * 86400


def load_stations(networks: Iterable[str] = SNOW_NETWORKS) -> list[Station]:
    """Load and cache the AWDB station list, filtered to snow-bearing networks."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if _stations_cache_fresh():
        raw = json.loads(STATIONS_CACHE.read_text())
    else:
        url = f"{AWDB_BASE}/stations"
        # Request minimal payload, no forecast points / reservoirs / elements.
        params = {
            "returnForecastPointMetadata": "false",
            "returnReservoirMetadata": "false",
            "returnStationElements": "false",
        }
        r = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=120)
        r.raise_for_status()
        raw = r.json()
        STATIONS_CACHE.write_text(json.dumps(raw))

    nets = set(networks)
    stations: list[Station] = []
    for obj in raw:
        if obj.get("networkCode") not in nets:
            continue
        if obj.get("latitude") is None or obj.get("longitude") is None:
            continue
        try:
            stations.append(Station.from_api(obj))
        except (KeyError, TypeError, ValueError):
            continue
    return stations


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def nearest_stations(lat: float, lon: float, stations: list[Station], k: int = 5) -> list[tuple[float, Station]]:
    """Return the k nearest stations as (distance_km, station) sorted ascending."""
    scored = [(_haversine_km(lat, lon, s.lat, s.lon), s) for s in stations]
    scored.sort(key=lambda t: t[0])
    return scored[:k]


def latest_snow(triplet: str, days_back: int = 7) -> dict:
    """Return the most recent WTEQ and SNWD readings for a station.

    Output shape:
      {
        "WTEQ": {"value": float|None, "date": "YYYY-MM-DD"|None, "unit": "in"},
        "SNWD": {"value": float|None, "date": "YYYY-MM-DD"|None, "unit": "in"},
      }
    """
    end = date.today()
    begin = end - timedelta(days=days_back)
    url = f"{AWDB_BASE}/data"
    params = {
        "stationTriplets": triplet,
        "elements": "WTEQ,SNWD",
        "duration": "DAILY",
        "beginDate": begin.isoformat(),
        "endDate": end.isoformat(),
        "returnFlags": "false",
        "returnOriginalValues": "false",
        "returnSuspectData": "false",
    }
    r = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=60)
    r.raise_for_status()
    payload = r.json()
    out: dict[str, dict] = {
        "WTEQ": {"value": None, "date": None, "unit": "in"},
        "SNWD": {"value": None, "date": None, "unit": "in"},
    }
    if not payload:
        return out
    for stream in payload[0].get("data", []):
        elem = stream.get("stationElement", {})
        code = elem.get("elementCode")
        if code not in out:
            continue
        unit = elem.get("storedUnitCode", "in")
        # Pick the most recent non-null reading.
        latest = None
        for v in stream.get("values", []):
            if v.get("value") is None:
                continue
            d = v.get("date")
            if latest is None or (d and d > latest["date"]):
                latest = {"value": v["value"], "date": d}
        if latest:
            out[code] = {"value": latest["value"], "date": latest["date"], "unit": unit}
    return out


def nearest_active(lat: float, lon: float, stations: list[Station], k: int = 5) -> tuple[Station, float, dict] | None:
    """Find the nearest station with a recent snow reading.

    Returns (station, distance_km, snow_readings) or None.
    """
    for dist, st in nearest_stations(lat, lon, stations, k=k):
        try:
            snow = latest_snow(st.triplet)
        except requests.RequestException:
            continue
        has_data = (
            snow.get("WTEQ", {}).get("value") is not None
            or snow.get("SNWD", {}).get("value") is not None
        )
        if has_data:
            return st, dist, snow
    return None
