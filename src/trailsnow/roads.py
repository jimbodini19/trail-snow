"""USFS road status near a trailhead.

Queries two ArcGIS FeatureLayers from the USDA Forest Service Enterprise
Data Warehouse:

  - Layer 0: National Forest System Roads currently OPEN (with maintenance
    level, surface type, "open for use to" attribute).
  - Layer 1: National Forest System Roads currently CLOSED to motorized
    uses (per the EDW closed-roads dataset).

Both layers are keyless, public, and standard ArcGIS REST. We do a small
buffered point-in-polygon-style spatial query around the trailhead and
return the nearest road in each layer plus enough metadata for the report
to classify access.

Combine with the SNODAS trailhead-snow proxy:
  - CLOSED road found within X meters of trailhead -> definitely gated.
  - OPEN paved/passenger-car road found close -> definitely drivable
    (overrides a SNODAS-snowy reading, e.g. Paradise NPS roads in winter).
  - No road feature found nearby -> fall back to SNODAS proxy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import requests

OPEN_LAYER = "https://apps.fs.usda.gov/arcx/rest/services/EDW/EDW_RoadBasic_01/MapServer/0/query"
CLOSED_LAYER = "https://apps.fs.usda.gov/arcx/rest/services/EDW/EDW_RoadBasic_01/MapServer/1/query"
USER_AGENT = "trail-snow/0.3 (contact: jimmy@guidedgrowthmktg.com)"
CACHE_DIR = Path("data/cache/roads")

# Search radius around the trailhead for nearest road. 2 km picks up the
# access spur and the road it connects to in almost all cases.
DEFAULT_RADIUS_M = 2000

# Maintenance-level strings that imply you can probably drive a normal car.
DRIVABLE_LEVELS = {
    "5 - HIGH DEGREE OF USER COMFORT",
    "4 - MODERATE DEGREE OF USER COMFORT",
    "3 - SUITABLE FOR PASSENGER CARS",
}
# Levels 1 and 2 are high-clearance only or basically closed.


@dataclass
class RoadHit:
    name: str
    road_id: str
    maint_level: str | None
    open_for_use_to: str | None
    surface_type: str | None
    jurisdiction: str | None
    distance_m: float | None  # ArcGIS doesn't return distance; we ask "within X"


def _cache_path(lat: float, lon: float, radius_m: int, layer: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = f"{round(lat, 4)}_{round(lon, 4)}_{radius_m}_{layer}.json"
    return CACHE_DIR / key


def _query(url: str, lat: float, lon: float, radius_m: int) -> list[dict]:
    """Spatial-intersect query around (lat, lon). Returns feature attributes."""
    params = {
        "geometry": f"{lon},{lat}",
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "distance": str(radius_m),
        "units": "esriSRUnit_Meter",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "name,id,oper_maint_level,openforuseto,surface_type,jurisdiction",
        "returnGeometry": "false",
        "resultRecordCount": "10",
        "f": "json",
    }
    r = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=60)
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"ArcGIS error: {data['error']}")
    return [f.get("attributes", {}) for f in data.get("features", [])]


def _first(attrs: dict) -> RoadHit | None:
    if not attrs:
        return None
    return RoadHit(
        name=str(attrs.get("name") or "").strip() or "(unnamed)",
        road_id=str(attrs.get("id") or "").strip() or "?",
        maint_level=attrs.get("oper_maint_level"),
        open_for_use_to=attrs.get("openforuseto"),
        surface_type=attrs.get("surface_type"),
        jurisdiction=attrs.get("jurisdiction"),
        distance_m=None,
    )


def query_road_status(lat: float, lon: float, radius_m: int = DEFAULT_RADIUS_M) -> dict:
    """Return {"open": RoadHit|None, "closed": RoadHit|None} for the trailhead."""
    cache = _cache_path(lat, lon, radius_m, "both")
    if cache.exists():
        try:
            cached = json.loads(cache.read_text())
            return {
                "open": _first(cached["open_attrs"]) if cached.get("open_attrs") else None,
                "closed": _first(cached["closed_attrs"]) if cached.get("closed_attrs") else None,
            }
        except (json.JSONDecodeError, KeyError):
            pass

    try:
        open_feats = _query(OPEN_LAYER, lat, lon, radius_m)
    except (requests.RequestException, RuntimeError):
        open_feats = []
    try:
        closed_feats = _query(CLOSED_LAYER, lat, lon, radius_m)
    except (requests.RequestException, RuntimeError):
        closed_feats = []

    cache.write_text(json.dumps({
        "open_attrs": open_feats[0] if open_feats else None,
        "closed_attrs": closed_feats[0] if closed_feats else None,
    }))

    return {
        "open": _first(open_feats[0]) if open_feats else None,
        "closed": _first(closed_feats[0]) if closed_feats else None,
    }


def classify_access(
    trailhead_snow_cm: float | None,
    road_status: dict,
    snow_threshold_cm: float = 8.0,
) -> tuple[str, str, str]:
    """Combine SNODAS-at-trailhead with FS road status.

    Returns (badge_text, css_class, sub_text). Logic priority:
      1. If FS reports a CLOSED road right at the trailhead -> GATED.
      2. If FS reports an OPEN passenger-car or paved road -> DRIVABLE
         (regardless of SNODAS, since maintained roads are plowed).
      3. Otherwise fall back to SNODAS: >= 8 cm of snow at trailhead -> blocked.
      4. Otherwise -> likely open.
    """
    closed = road_status.get("closed")
    if closed is not None:
        sub = f"FS road {closed.road_id} {closed.name} is currently closed to motorized use"
        return ("ACCESS GATED", "badge snowy", sub)

    open_road = road_status.get("open")
    if open_road is not None and (open_road.maint_level or "") in DRIVABLE_LEVELS:
        sub = (
            f"FS road {open_road.road_id} {open_road.name} is open "
            f"({(open_road.maint_level or '').lower()})"
        )
        return ("ACCESS DRIVABLE", "badge open", sub)

    if trailhead_snow_cm is not None and trailhead_snow_cm >= snow_threshold_cm:
        return (
            "ACCESS LIKELY BLOCKED",
            "badge snowy",
            f"no FS road status found, but trailhead has {trailhead_snow_cm:.0f} cm of snow",
        )
    if trailhead_snow_cm is not None:
        sub = f"no FS road status found, trailhead has {trailhead_snow_cm:.0f} cm of snow"
        return ("ACCESS LIKELY OPEN", "badge open", sub)
    return ("ACCESS UNKNOWN", "badge unknown", "no road or snow data at trailhead")
