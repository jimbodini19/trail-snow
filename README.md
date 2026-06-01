# trail-snow

Estimates current snow conditions along hiking trails. Starts with WA / the
Cascades. Answers: "for a given trail, is it likely snowed in right now, and
roughly what fraction of its length?"

This is an estimate, not a verdict. Trailhead access (gated FS roads, unplowed
forest roads) is a separate problem and is intentionally out of scope until v3.

## Status

- **v1 (built)**: pulls trail geometry from OpenStreetMap (Overpass), finds
  the nearest active SNOTEL station, prints current SWE and snow depth next to
  the trail. Crude on purpose. SNOTEL stations are rarely at trail elevation,
  so treat the number as a coarse indicator. Renders an HTML report.
- **v2 (built)**: samples points every ~300 m along each trail line, looks
  up SNODAS snow depth at each, gets USGS 3DEP elevation, computes a
  snowed-in fraction at a tunable depth threshold (default 10 cm).
  Renders an HTML report with per-trail fraction + inline depth sparkline.
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

Render a self-contained Leaflet map of the run (open in any browser, no install):

```
python -m trailsnow.v1 --all --map out/v1.html
```

Run a custom area by Overpass query (named relation or bbox):

```
python -m trailsnow.v1 --bbox 46.83,-121.78,46.86,-121.72 --name "Skyline Trail"
```

A pre-rendered snapshot built from real AWDB data on 2026-06-01 ships at
`sample_runs/v1_report_2026-06-01.html`.

## Use (v2)

```
python -m trailsnow.v2 --all --report out/v2.html
python -m trailsnow.v2 --seed skyline_loop_rainier
python -m trailsnow.v2 --seed lake_22_mountain_loop --threshold-cm 15
```

First run downloads the latest available SNODAS daily masked CONUS file
(roughly 70 MB tar, decoded to ~46 MB int16 array) and caches it as
`data/cache/snodas/snowdepth_YYYYMMDD.npy`. Subsequent runs reuse the
cache. Elevation lookups go to USGS EPQS one point at a time with a small
sleep between calls, also cached.

NSIDC runs SNODAS at "Basic" service level. If the most recent day isn't
posted yet, v2 walks back day-by-day up to 7 days and uses the latest one
it can fetch. The report shows which day's grid was used.

## Hosting on GitHub Pages

The v2 report is a self-contained HTML file, so Pages is one-click hosting.

1. Create an empty repo on github.com (suggest name `trail-snow`).
2. From this folder, wire it up and push:

   ```
   git add -A && git commit -m "v1+v2+v3"
   git branch -M main
   git remote add origin https://github.com/<your-user>/trail-snow.git
   git push -u origin main
   ```

3. Build the report into `docs/` and push it:

   ```
   ./scripts/publish.sh --push
   ```

4. On github.com -> repo -> Settings -> Pages, set Source = `main` branch,
   folder = `/docs`. Wait ~30 seconds. The report goes live at
   `https://<your-user>.github.io/trail-snow/`.

5. Whenever you want a fresh report, run `./scripts/publish.sh --push`
   and Pages redeploys automatically.

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
