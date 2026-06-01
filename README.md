# trail-snow

Estimates current snow conditions along hiking trails. Starts with WA / the
Cascades. Answers: "for a given trail, is it likely snowed in right now, and
roughly what fraction of its length?"

This is an estimate, not a verdict. Trailhead access (gated FS roads, unplowed
forest roads) is a separate problem and is intentionally out of scope until v3.

## Status

- **v1 (current)**: pulls trail geometry from OpenStreetMap (Overpass), finds
  the nearest active SNOTEL station, prints current SWE and snow depth next to
  the trail. Crude on purpose. SNOTEL stations are rarely at trail elevation,
  so treat the number as a coarse indicator.
- **v2 (next)**: sample points every 200 to 400 m along each trail, look up
  SNODAS snow depth at each, get USGS 3DEP elevation, compute snowed-in
  fraction at a tunable depth threshold.
- **v3 (later, separate)**: trailhead road access flag using Forest Service
  road status sources. Reported alongside snow, never folded into it.

## Data sources (all keyless, all verified live 2026-06-01)

- **Trail geometry**: OpenStreetMap via [Overpass API](https://overpass-api.de/api/interpreter).
  Query for `highway=path|footway|track` ways in a bounding box or by name.
- **Point snow telemetry**: [NRCS AWDB REST API v1](https://wcc.sc.egov.usda.gov/awdbRestApi/swagger-ui/index.html).
  Station metadata from `/stations`, current readings from `/data`. Snow
  elements: `WTEQ` (snow water equivalent, in inches), `SNWD` (snow depth, in
  inches). Active networks for snow: `SNTL` (SNOTEL automated) and `SNTLT`
  (SNOTEL light).
- **Gridded snow model (v2)**: SNODAS daily 1 km CONUS grids from NSIDC,
  dataset G02158, served over HTTPS at
  https://noaadata.apps.nsidc.org/NOAA/G02158/. Flat binary 16-bit signed
  big-endian, separate header file, WGS84. NSIDC runs SNODAS at the "Basic"
  service level, so cache aggressively and handle outages.
- **Elevation (v2)**: USGS 3DEP via the [Elevation Point Query Service](https://epqs.nationalmap.gov/v1/json).

## Install

Requires Python 3.10+.

```
cd trail-snow
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

v1 only needs `requests`. v2 adds `numpy`, `rasterio`, `shapely`, `geopandas`.

## Use (v1)

Run against a single seed trail by ID:

```
python -m trailsnow.v1 --seed skyline_loop_rainier
```

Run all seeds:

```
python -m trailsnow.v1 --all
```

Run a custom area by Overpass query (named relation or bbox):

```
python -m trailsnow.v1 --bbox 46.83,-121.78,46.86,-121.72 --name "Skyline Trail"
```

The SNOTEL station catalog is cached at `data/cache/snotel_stations.json` on
first run (the AWDB stations endpoint returns the full national list, so
caching is mandatory). Delete the file to force a refresh.

## Seeds

`seeds/trails.yaml` lists known trails to sanity-check against. Mix of high
Cascades trails that should clearly be snowy and lower-elevation trails near
Moscow, ID that probably are not, plus a couple of borderline cases.

## Notes for future work

- AWDB query filters (`stateCds=WA&networkCds=SNTL`) appeared to be ignored by
  the server in early testing, so v1 fetches the full station list once and
  filters client-side. Revisit the filter behavior when the swagger docs are
  more reliable.
- For v2, SNODAS files are daily and large. Plan to cache the most recent
  successful day per region and label staleness in the output.
- Overpass rate limits are real. The v1 client uses a single bbox query per
  trail and writes results to `data/cache/overpass/`.
