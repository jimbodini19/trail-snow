"""SNODAS daily masked CONUS grid: download, decode, sample.

SNODAS masked grid specs (NSIDC G02158, v1):
  - 6935 cols x 3351 rows of int16 big-endian, no header inside the .dat file
  - cell size: 30 arc-seconds (0.00833333... degrees)
  - lower-left corner of the lower-left pixel: (-124.73375, 24.95) WGS84
  - upper-right corner of the upper-right pixel: (-66.94208, 52.87083)
  - nodata: -9999
  - depth values in mm (no scale factor needed for snow depth product 1036)

Layout of the daily archive at:
  https://noaadata.apps.nsidc.org/NOAA/G02158/masked/YYYY/MM_Mon/SNODAS_YYYYMMDD.tar

Inside the tar, the snow depth file is:
  us_ssmv11036tS__T0001TTNATSYYYYMMDD05HP001.dat.gz

NSIDC runs SNODAS at "Basic" service level, so production lag is 1 to 3 days
and outages happen. Always fall back to older days. We cache decoded arrays
on disk per date so repeated runs are fast.
"""

from __future__ import annotations

import gzip
import io
import tarfile
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import requests

MASKED_BASE = "https://noaadata.apps.nsidc.org/NOAA/G02158/masked"
USER_AGENT = "trail-snow/0.2 (https://example.local)"

# Masked grid constants.
COLS = 6935
ROWS = 3351
CELL_SIZE = 0.00833333333333  # degrees, == 30 arc-seconds
LL_LON = -124.73375
LL_LAT = 24.95
NODATA = -9999

# Geographic span (pixel-edge based).
MIN_LON = LL_LON
MAX_LON = LL_LON + COLS * CELL_SIZE  # ~ -66.942
MIN_LAT = LL_LAT
MAX_LAT = LL_LAT + ROWS * CELL_SIZE  # ~ 52.871

CACHE_DIR = Path("data/cache/snodas")
MONTH_ABBR = ["", "01_Jan", "02_Feb", "03_Mar", "04_Apr", "05_May", "06_Jun",
              "07_Jul", "08_Aug", "09_Sep", "10_Oct", "11_Nov", "12_Dec"]


def _tar_url(d: date) -> str:
    return f"{MASKED_BASE}/{d.year}/{MONTH_ABBR[d.month]}/SNODAS_{d:%Y%m%d}.tar"


def _depth_member_name(d: date) -> str:
    return f"us_ssmv11036tS__T0001TTNATS{d:%Y%m%d}05HP001.dat.gz"


def _cache_path(d: date) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"snowdepth_{d:%Y%m%d}.npy"


def _download_and_extract_depth(d: date) -> np.ndarray:
    """Download the SNODAS tar for date d, extract the snow depth grid as int16."""
    url = _tar_url(d)
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=300)
    r.raise_for_status()

    depth_name = _depth_member_name(d)
    with tarfile.open(fileobj=io.BytesIO(r.content), mode="r:") as tf:
        member = None
        for m in tf.getmembers():
            if m.name.endswith(depth_name) or m.name == depth_name:
                member = m
                break
        if member is None:
            raise RuntimeError(f"depth file {depth_name!r} not found in {url}")
        gz_bytes = tf.extractfile(member).read()

    raw = gzip.decompress(gz_bytes)
    arr = np.frombuffer(raw, dtype=">i2").astype(np.int16)
    if arr.size != COLS * ROWS:
        raise RuntimeError(
            f"unexpected SNODAS grid size {arr.size}, expected {COLS * ROWS}"
        )
    return arr.reshape((ROWS, COLS))


def load_depth(d: date | None = None, max_lookback_days: int = 7) -> tuple[np.ndarray, date]:
    """Return (depth_grid_mm, actual_date_used).

    Tries d, then walks back day-by-day up to max_lookback_days when the file
    is unavailable (404, network, partial outage). Uses a per-date npy cache.
    """
    target = d or date.today() - timedelta(days=1)
    last_err: Exception | None = None
    for offset in range(max_lookback_days + 1):
        attempt = target - timedelta(days=offset)
        cache = _cache_path(attempt)
        if cache.exists():
            return np.load(cache), attempt
        try:
            grid = _download_and_extract_depth(attempt)
            np.save(cache, grid)
            return grid, attempt
        except (requests.RequestException, RuntimeError) as e:
            last_err = e
            continue
    raise RuntimeError(
        f"no SNODAS file available within {max_lookback_days} days of {target}: {last_err}"
    )


def latlon_to_pixel(lat: float, lon: float) -> tuple[int, int]:
    """Return (row, col) pixel for a WGS84 point. Raises if outside grid."""
    if not (MIN_LON <= lon <= MAX_LON and MIN_LAT <= lat <= MAX_LAT):
        raise ValueError(f"point ({lat}, {lon}) outside SNODAS masked CONUS extent")
    col = int((lon - LL_LON) / CELL_SIZE)
    # row index is from the TOP, so flip: row 0 is at MAX_LAT.
    row = int((MAX_LAT - lat) / CELL_SIZE)
    col = min(max(col, 0), COLS - 1)
    row = min(max(row, 0), ROWS - 1)
    return row, col


def depth_mm_at(grid: np.ndarray, lat: float, lon: float) -> float | None:
    """Sample SNODAS depth at a point. Returns mm, or None if nodata."""
    r, c = latlon_to_pixel(lat, lon)
    v = int(grid[r, c])
    if v == NODATA:
        return None
    return float(v)


def depths_along(grid: np.ndarray, points: list[tuple[float, float]]) -> list[float | None]:
    """Sample many points in one call. None for any nodata cell."""
    out: list[float | None] = []
    for lat, lon in points:
        try:
            out.append(depth_mm_at(grid, lat, lon))
        except ValueError:
            out.append(None)
    return out
