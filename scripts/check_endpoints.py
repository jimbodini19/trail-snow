"""Quick liveness check for the four upstream data sources.

Run before opening an issue if v1 starts behaving oddly. Exits non-zero if
any required endpoint is unreachable. Does not parse responses, just
confirms HTTP 200.

    python scripts/check_endpoints.py
"""

from __future__ import annotations

import sys
import requests

CHECKS = [
    (
        "Overpass interpreter",
        "https://overpass-api.de/api/interpreter",
        {"params": {"data": "[out:json];out 1;"}, "timeout": 30},
    ),
    (
        "NRCS AWDB stations",
        "https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1/stations",
        {
            "params": {
                "stationTriplets": "679:WA:SNTL",
                "returnForecastPointMetadata": "false",
                "returnReservoirMetadata": "false",
                "returnStationElements": "false",
            },
            "timeout": 30,
        },
    ),
    (
        "NRCS AWDB data",
        "https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1/data",
        {
            "params": {
                "stationTriplets": "679:WA:SNTL",
                "elements": "WTEQ",
                "duration": "DAILY",
                "beginDate": "2026-05-25",
                "endDate": "2026-06-01",
            },
            "timeout": 30,
        },
    ),
    (
        "SNODAS host (v2 only)",
        "https://noaadata.apps.nsidc.org/NOAA/G02158/",
        {"timeout": 30},
    ),
    (
        "USGS 3DEP EPQS (v2 only)",
        "https://epqs.nationalmap.gov/v1/json",
        {
            "params": {"x": -121.7, "y": 46.85, "units": "Meters", "wkid": 4326},
            "timeout": 30,
        },
    ),
]


def main() -> int:
    failures = 0
    for name, url, kwargs in CHECKS:
        try:
            r = requests.get(url, **kwargs)
            ok = r.status_code == 200
            print(f"  {'OK ' if ok else 'FAIL'}  {name}  HTTP {r.status_code}")
            if not ok:
                failures += 1
        except Exception as e:
            print(f"  FAIL  {name}  {type(e).__name__}: {e}")
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
