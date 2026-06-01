"""Render a v1 run as a self-contained HTML report.

Lists every seed trail with an open/snowed-in badge and current snow depth,
sorted snowiest first. No external CDN, no JavaScript needed. Open the file
in any browser.

Status thresholds (per v2-locked 10 cm rule):
  - SNWD >= 4 in (~10 cm)         -> "likely snowed in"
  - 1 in <= SNWD < 4 in           -> "patchy"
  - SNWD < 1 in                   -> "likely open"
  - no nearby station or no data  -> "unknown"

Open and closed are estimates, not verdicts. The nearest SNOTEL is often at
a different elevation than the trail. v2 will give per-segment readings using
SNODAS grid + actual trail elevation.
"""

from __future__ import annotations

from datetime import date
from html import escape


def _classify(snwd_in: float | None) -> tuple[str, str, str]:
    """Return (badge_text, css_class, plain_label)."""
    if snwd_in is None:
        return ("UNKNOWN", "badge unknown", "no nearby station")
    if snwd_in >= 4:
        return ("LIKELY SNOWED IN", "badge snowy", "likely snowed in")
    if snwd_in >= 1:
        return ("PATCHY", "badge patchy", "patchy snow possible")
    return ("LIKELY OPEN", "badge open", "likely open / mostly bare")


def _sort_key(entry: dict) -> tuple[int, float]:
    """Snowiest first, then patchy, then bare, then unknown."""
    snow = entry.get("snow") or {}
    snwd = (snow.get("SNWD") or {}).get("value")
    if snwd is None:
        return (3, 0.0)
    if snwd >= 4:
        return (0, -snwd)
    if snwd >= 1:
        return (1, -snwd)
    return (2, -snwd)


def render_map(entries: list[dict]) -> str:
    rows = []
    for e in sorted(entries, key=_sort_key):
        snow = e.get("snow") or {}
        snwd_v = (snow.get("SNWD") or {}).get("value")
        snwd_d = (snow.get("SNWD") or {}).get("date")
        wteq_v = (snow.get("WTEQ") or {}).get("value")
        badge_text, badge_cls, _ = _classify(snwd_v)

        station_block = '<div class="station muted">No SNOTEL station within search radius.</div>'
        if e.get("station"):
            st = e["station"]
            elev = f"{st['elevation_ft']:.0f} ft" if st.get("elevation_ft") is not None else "elev n/a"
            station_block = (
                f'<div class="station">'
                f'<span class="lbl">nearest SNOTEL</span> '
                f'<b>{escape(st["name"])}</b> '
                f'<span class="muted">({escape(st["triplet"])})</span><br>'
                f'<span class="muted">{st["distance_km"]:.1f} km from trail centroid &middot; {escape(elev)}</span>'
                f"</div>"
            )

        snwd_display = "&mdash;" if snwd_v is None else f"{snwd_v} in <span class=\"muted\">({snwd_v * 2.54:.0f} cm)</span>"
        wteq_display = "&mdash;" if wteq_v is None else f"{wteq_v} in"
        reading_date = snwd_d or "n/a"

        rows.append(
            f'''<article class="trail">
  <header>
    <div class="title">
      <h2>{escape(e["seed_name"])}</h2>
      <div class="area">{escape(e.get("area", ""))}</div>
    </div>
    <span class="{badge_cls}">{badge_text}</span>
  </header>
  <div class="grid">
    <div class="metric">
      <div class="metric-label">snow depth</div>
      <div class="metric-value">{snwd_display}</div>
    </div>
    <div class="metric">
      <div class="metric-label">snow water equivalent</div>
      <div class="metric-value">{wteq_display}</div>
    </div>
    <div class="metric">
      <div class="metric-label">reading from</div>
      <div class="metric-value small">{escape(reading_date)}</div>
    </div>
  </div>
  {station_block}
  <div class="expected muted">expected: {escape(e.get("expected", ""))}</div>
</article>'''
        )

    counts = {"snowy": 0, "patchy": 0, "open": 0, "unknown": 0}
    for e in entries:
        snwd_v = ((e.get("snow") or {}).get("SNWD") or {}).get("value")
        if snwd_v is None:
            counts["unknown"] += 1
        elif snwd_v >= 4:
            counts["snowy"] += 1
        elif snwd_v >= 1:
            counts["patchy"] += 1
        else:
            counts["open"] += 1

    today = date.today().isoformat()
    body = "\n".join(rows)
    summary = (
        f'<span class="pill snowy">{counts["snowy"]} snowed in</span>'
        f'<span class="pill patchy">{counts["patchy"]} patchy</span>'
        f'<span class="pill open">{counts["open"]} open</span>'
        f'<span class="pill unknown">{counts["unknown"]} unknown</span>'
    )
    return _TEMPLATE.replace("__BODY__", body).replace("__SUMMARY__", summary).replace("__DATE__", today)


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>trail-snow report</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         max-width: 820px; margin: 32px auto; padding: 0 20px;
         background: #fafafa; color: #1a1a1a; line-height: 1.45; }
  h1 { font-size: 22px; margin: 0 0 4px; }
  .sub { color: #666; font-size: 13px; margin-bottom: 18px; }
  .summary { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 24px; }
  .pill { font-size: 12px; padding: 4px 10px; border-radius: 999px; font-weight: 600; }
  .pill.snowy   { background: #fde2e2; color: #8a1c1c; }
  .pill.patchy  { background: #fdecc8; color: #8b5a00; }
  .pill.open    { background: #d4f0d4; color: #1e6b1e; }
  .pill.unknown { background: #e2e2e2; color: #555; }
  .trail { background: white; border: 1px solid #e5e5e5; border-radius: 10px;
           padding: 18px 20px; margin-bottom: 14px; box-shadow: 0 1px 2px rgba(0,0,0,0.03); }
  .trail header { display: flex; justify-content: space-between; align-items: flex-start;
                  gap: 16px; margin-bottom: 14px; }
  .trail h2 { font-size: 17px; margin: 0; }
  .trail .area { color: #666; font-size: 12px; margin-top: 2px; }
  .badge { font-size: 11px; font-weight: 700; padding: 5px 10px; border-radius: 4px;
           letter-spacing: 0.4px; white-space: nowrap; }
  .badge.snowy   { background: #d73027; color: white; }
  .badge.patchy  { background: #f4a92e; color: white; }
  .badge.open    { background: #1a9850; color: white; }
  .badge.unknown { background: #888; color: white; }
  .grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px;
          margin-bottom: 12px; }
  .metric { background: #f5f5f5; padding: 10px 12px; border-radius: 6px; }
  .metric-label { font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px;
                  color: #666; margin-bottom: 4px; }
  .metric-value { font-size: 16px; font-weight: 600; }
  .metric-value.small { font-size: 13px; font-weight: 500; color: #333; }
  .station { font-size: 13px; padding: 8px 0; border-top: 1px solid #eee; }
  .station .lbl { color: #666; font-size: 11px; text-transform: uppercase;
                  letter-spacing: 0.4px; margin-right: 4px; }
  .expected { font-size: 12px; padding-top: 8px; border-top: 1px solid #eee; margin-top: 8px; }
  .muted { color: #777; }
  footer { font-size: 11px; color: #777; margin-top: 30px; line-height: 1.6; }
  @media (prefers-color-scheme: dark) {
    body { background: #1a1a1a; color: #eee; }
    .trail { background: #262626; border-color: #333; }
    .metric { background: #1f1f1f; }
    .station, .expected { border-color: #333; }
    .muted, .sub, .area, .metric-label, .station .lbl { color: #aaa; }
  }
</style>
</head>
<body>
<h1>trail-snow report</h1>
<div class="sub">v1 estimate, based on the single nearest SNOTEL station to each trail. Generated __DATE__.</div>
<div class="summary">__SUMMARY__</div>
__BODY__
<footer>
  Status thresholds: <b>snowed in</b> &ge; 4 in (10 cm) snow depth &middot;
  <b>patchy</b> 1 to 4 in &middot; <b>open</b> &lt; 1 in.<br>
  v1 limitation: the nearest SNOTEL is often at a different elevation than the
  trail. A "likely open" or "patchy" reading from a pass-level station does
  not rule out lingering snow on a higher segment of the same trail.<br>
  Trailhead road access is a separate problem and is not folded into this estimate.<br>
  Data: NRCS AWDB REST API (SNOTEL) + OpenStreetMap (trail geometry).
</footer>
</body>
</html>
"""
