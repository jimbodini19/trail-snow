"""v2 HTML report: per-trail snowed-in fraction with inline depth sparkline.

Same self-contained-HTML approach as the v1 report. No CDN, no JS.
Sparkline is an inline SVG of snow depth (cm) vs cumulative distance along
the trail. Threshold line is drawn so you can eyeball how much of the trail
sits above the cutoff.
"""

from __future__ import annotations

from datetime import date
from html import escape


def _classify_fraction(frac: float | None) -> tuple[str, str]:
    if frac is None:
        return ("UNKNOWN", "badge unknown")
    pct = frac * 100
    if pct >= 60:
        return (f"SNOWED IN ({pct:.0f}%)", "badge snowy")
    if pct >= 20:
        return (f"PARTLY SNOWY ({pct:.0f}%)", "badge patchy")
    return (f"LIKELY OPEN ({pct:.0f}%)", "badge open")


# Threshold for the SNODAS-at-trailhead fallback when FS road status is unknown.
ACCESS_THRESHOLD_CM = 8.0

DRIVABLE_LEVELS = {
    "5 - HIGH DEGREE OF USER COMFORT",
    "4 - MODERATE DEGREE OF USER COMFORT",
    "3 - SUITABLE FOR PASSENGER CARS",
}


def _classify_access(trailhead: dict | None) -> tuple[str, str, str]:
    """Combine FS road status with SNODAS-at-trailhead.

    Priority:
      1. FS reports a CLOSED road near trailhead -> GATED.
      2. FS reports an OPEN paved/passenger-car road -> DRIVABLE
         (overrides SNODAS, because maintained roads get plowed).
      3. Fall back to SNODAS snow at trailhead.
    """
    if not trailhead:
        return ("ACCESS UNKNOWN", "badge unknown", "no trailhead sample")
    depth = trailhead.get("depth_cm")
    elev = trailhead.get("elevation_m")
    elev_str = f"{elev:.0f} m" if elev is not None else "elev n/a"
    rs = trailhead.get("road_status") or {}

    closed = rs.get("closed") if isinstance(rs, dict) else None
    if closed:
        return (
            "ACCESS GATED",
            "badge snowy",
            f"FS road {closed.get('road_id','?')} {closed.get('name','')} is closed to motorized use",
        )

    open_road = rs.get("open") if isinstance(rs, dict) else None
    if open_road and (open_road.get("maint_level") or "") in DRIVABLE_LEVELS:
        ml = (open_road.get("maint_level") or "").lower()
        return (
            "ACCESS DRIVABLE",
            "badge open",
            f"FS road {open_road.get('road_id','?')} {open_road.get('name','')} is open ({ml})",
        )

    if depth is None:
        return ("ACCESS UNKNOWN", "badge unknown", "no FS road status, no trailhead snow data")

    if depth >= ACCESS_THRESHOLD_CM:
        return (
            "ACCESS LIKELY BLOCKED",
            "badge snowy",
            f"no FS road match, trailhead at {elev_str} shows {depth:.0f} cm of snow on SNODAS",
        )
    return (
        "ACCESS LIKELY OPEN",
        "badge open",
        f"no FS road match, trailhead at {elev_str} shows {depth:.0f} cm of snow on SNODAS",
    )


def _sparkline_svg(depths_mm: list[float | None], cum_m: list[float] | None,
                   threshold_cm: float, width: int = 280, height: int = 56) -> str:
    pad = 4
    valid = [(i, d / 10.0) for i, d in enumerate(depths_mm) if d is not None]
    if not valid:
        return f'<svg width="{width}" height="{height}"></svg>'
    n = len(depths_mm)
    max_cm = max(d for _, d in valid)
    y_max = max(max_cm, threshold_cm * 1.5, 10.0)
    inner_w = width - 2 * pad
    inner_h = height - 2 * pad

    def x_of(i): return pad + (inner_w * i / max(1, n - 1))
    def y_of(cm): return pad + inner_h - (inner_h * (cm / y_max))

    # Filled area for snow depth.
    points = [f"{x_of(i):.1f},{y_of(d/10.0):.1f}" for i, d in enumerate(depths_mm) if d is not None]
    poly = f'<polyline fill="none" stroke="#4a9eff" stroke-width="1.5" points="{" ".join(points)}"/>'
    # Threshold line.
    th_y = y_of(threshold_cm)
    th = (f'<line x1="{pad}" y1="{th_y:.1f}" x2="{width-pad}" y2="{th_y:.1f}" '
          f'stroke="#ff6b5e" stroke-width="1" stroke-dasharray="3 3"/>')
    th_label = (f'<text x="{width-pad-2}" y="{max(th_y-2, 10):.1f}" '
                f'text-anchor="end" font-size="9" fill="#ff6b5e">{threshold_cm:.0f} cm</text>')
    # Max label.
    max_label = (f'<text x="{pad+2}" y="11" font-size="9" fill="#8a8a90">max {max_cm:.0f} cm</text>')
    return (f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
            f'xmlns="http://www.w3.org/2000/svg">{th}{poly}{th_label}{max_label}</svg>')


_STATE_RE = None  # lazy compile

def _state_of(area: str) -> str:
    """Extract a state code from the area string. 'WA - Foo' -> 'WA', 'ID/WA - Foo' -> 'ID'."""
    head = (area or "").split(" - ")[0].strip()
    return head.split("/")[0].strip().upper()


def _status_key(r: dict) -> str:
    if not r.get("ok") or r.get("snowed_in_fraction") is None:
        return "unknown"
    f = r["snowed_in_fraction"]
    if f >= 0.6: return "snowy"
    if f >= 0.2: return "patchy"
    return "open"


def render_v2_report(results: list[dict]) -> str:
    rows = []
    counts = {"snowy": 0, "patchy": 0, "open": 0, "unknown": 0}
    states_seen: set[str] = set()

    # Sort: snowiest first, then patchy, then open, then unknown.
    def sort_key(r):
        if not r["ok"] or r["snowed_in_fraction"] is None:
            return (3, 0.0)
        f = r["snowed_in_fraction"]
        if f >= 0.6: return (0, -f)
        if f >= 0.2: return (1, -f)
        return (2, -f)

    for r in sorted(results, key=sort_key):
        seed = r["seed"]
        ok = r["ok"]
        state_code = _state_of(seed.get("area", ""))
        states_seen.add(state_code)
        status_key = _status_key(r)
        if ok:
            frac = r["snowed_in_fraction"]
            badge_text, badge_cls = _classify_fraction(frac)
            access_text, access_cls, access_sub = _classify_access(r.get("trailhead"))
            if frac is None: counts["unknown"] += 1
            elif frac >= 0.6: counts["snowy"] += 1
            elif frac >= 0.2: counts["patchy"] += 1
            else: counts["open"] += 1
            ds = r["depth_stats"]
            depth_block = (
                f'<div class="metric"><div class="metric-label">depth median</div>'
                f'<div class="metric-value">{ds["median_cm"]:.0f} cm</div></div>'
                f'<div class="metric"><div class="metric-label">depth max</div>'
                f'<div class="metric-value">{ds["max_cm"]:.0f} cm</div></div>'
            ) if ds else (
                '<div class="metric"><div class="metric-label">depth</div>'
                '<div class="metric-value">&mdash;</div></div>'
            )
            elev_block = (
                f'<div class="metric"><div class="metric-label">elevation range</div>'
                f'<div class="metric-value small">{r["elev_min_m"]:.0f} to {r["elev_max_m"]:.0f} m</div></div>'
            ) if r["elev_min_m"] is not None else ""
            spark = _sparkline_svg(r["depths_mm"], None, r["threshold_cm"])
            sub_meta = (
                f'{r["n_ways"]} ways &middot; {r["total_length_m"]/1000:.1f} km &middot; '
                f'{r["n_samples_valid"]}/{r["n_samples_total"]} samples valid &middot; '
                f'SNODAS {r["grid_date"]}'
            )
        else:
            badge_text, badge_cls = ("NO DATA", "badge unknown")
            counts["unknown"] += 1
            depth_block = ""
            elev_block = ""
            spark = ""
            sub_meta = r.get("reason", "")
            access_text, access_cls, access_sub = ("ACCESS UNKNOWN", "badge unknown", "")

        # data-* attrs power the client-side filter and search.
        search_blob = escape(f'{seed.get("name","")} {seed.get("area","")} {seed.get("expected","")}'.lower())
        rows.append(f'''<article class="trail" data-status="{status_key}" data-state="{escape(state_code)}" data-search="{search_blob}">
  <header>
    <div class="title">
      <h2>{escape(seed["name"])}</h2>
      <div class="area">{escape(seed.get("area", ""))}</div>
    </div>
    <div class="badges">
      <span class="{badge_cls}">{badge_text}</span>
      <span class="{access_cls}" title="{escape(access_sub)}">{access_text}</span>
    </div>
  </header>
  <div class="spark">{spark}</div>
  <div class="grid">{depth_block}{elev_block}</div>
  <div class="meta muted">{sub_meta}</div>
  <div class="access muted">{escape(access_sub)}</div>
  <div class="expected muted">expected: {escape(seed.get("expected", ""))}</div>
</article>''')

    summary = (
        f'<span class="pill snowy">{counts["snowy"]} snowed in</span>'
        f'<span class="pill patchy">{counts["patchy"]} partly snowy</span>'
        f'<span class="pill open">{counts["open"]} likely open</span>'
        f'<span class="pill unknown">{counts["unknown"]} unknown</span>'
    )
    threshold_cm = next((r["threshold_cm"] for r in results if r.get("ok")), 10.0)
    grid_date = next((r["grid_date"] for r in results if r.get("ok")), "n/a")

    # State chips: only show states actually present in this run.
    state_order = ["WA", "ID", "OR", "MT"]
    extra = sorted(s for s in states_seen if s and s not in state_order)
    visible_states = [s for s in state_order if s in states_seen] + extra
    state_chips = "".join(
        f'<button class="chip state-chip active" data-state="{s}">{s}</button>'
        for s in visible_states
    )

    return (_TEMPLATE
            .replace("__BODY__", "\n".join(rows))
            .replace("__SUMMARY__", summary)
            .replace("__DATE__", date.today().isoformat())
            .replace("__THRESHOLD__", f"{threshold_cm:.0f}")
            .replace("__GRIDDATE__", grid_date)
            .replace("__STATECHIPS__", state_chips)
            .replace("__TOTAL__", str(len(results))))


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>trail-snow v2 report</title>
<style>
  :root {
    --bg: #0e0e10;
    --card: #1a1a1d;
    --metric: #232428;
    --border: #2a2b30;
    --text: #e8e8ea;
    --muted: #8a8a90;
    --subtle: #6a6a70;
    --accent: #4a9eff;
  }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         max-width: 820px; margin: 32px auto; padding: 0 20px;
         background: var(--bg); color: var(--text); line-height: 1.45; }
  h1 { font-size: 22px; margin: 0 0 4px; font-weight: 600; }
  .sub { color: var(--muted); font-size: 13px; margin-bottom: 18px; }
  .summary { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 24px; }
  .pill { font-size: 12px; padding: 5px 12px; border-radius: 999px; font-weight: 600; }
  .pill.snowy   { background: rgba(215, 48, 39, 0.18); color: #ff6b5e; }
  .pill.patchy  { background: rgba(244, 169, 46, 0.18); color: #f4a92e; }
  .pill.open    { background: rgba(26, 152, 80, 0.18); color: #4ade80; }
  .pill.unknown { background: rgba(255, 255, 255, 0.08); color: var(--muted); }
  .trail { background: var(--card); border: 1px solid var(--border); border-radius: 10px;
           padding: 18px 20px; margin-bottom: 14px; }
  .trail header { display: flex; justify-content: space-between; align-items: flex-start;
                  gap: 16px; margin-bottom: 12px; }
  .badges { display: flex; flex-direction: column; gap: 6px; align-items: flex-end; }
  .access { font-size: 11px; padding-top: 6px; }
  .trail h2 { font-size: 17px; margin: 0; font-weight: 600; }
  .trail .area { color: var(--muted); font-size: 12px; margin-top: 2px; }
  .badge { font-size: 11px; font-weight: 700; padding: 5px 10px; border-radius: 4px;
           letter-spacing: 0.4px; white-space: nowrap; color: white; }
  .badge.snowy   { background: #d73027; }
  .badge.patchy  { background: #f4a92e; }
  .badge.open    { background: #1a9850; }
  .badge.unknown { background: #4a4b50; color: var(--muted); }
  .spark { margin: 4px 0 12px; background: rgba(255,255,255,0.02); border-radius: 4px; padding: 2px 0; }
  .grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 8px; }
  .metric { background: var(--metric); padding: 10px 12px; border-radius: 6px; }
  .metric-label { font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px;
                  color: var(--muted); margin-bottom: 4px; }
  .metric-value { font-size: 16px; font-weight: 600; }
  .metric-value.small { font-size: 13px; font-weight: 500; }
  .meta, .expected { font-size: 12px; padding-top: 8px; border-top: 1px solid var(--border); margin-top: 8px; }
  .muted { color: var(--muted); }
  footer { font-size: 11px; color: var(--subtle); margin-top: 30px; line-height: 1.6; }

  .controls { position: sticky; top: 0; z-index: 10; background: var(--bg);
              padding: 10px 0 14px; margin: 0 -20px 18px; padding-left: 20px;
              padding-right: 20px; border-bottom: 1px solid var(--border); }
  #q { width: 100%; box-sizing: border-box; padding: 9px 12px; font-size: 13px;
       background: var(--card); border: 1px solid var(--border); border-radius: 6px;
       color: var(--text); outline: none; }
  #q:focus { border-color: var(--accent); }
  .chiprow { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; align-items: center; }
  .chipgroup { display: flex; flex-wrap: wrap; gap: 4px; }
  .chipgroup + .chipgroup { margin-left: 8px; padding-left: 8px; border-left: 1px solid var(--border); }
  .chip { font-size: 11px; padding: 4px 10px; border-radius: 999px; cursor: pointer;
          background: transparent; color: var(--muted); border: 1px solid var(--border);
          font-family: inherit; transition: all 0.1s; }
  .chip:hover { color: var(--text); border-color: var(--muted); }
  .chip.active { color: var(--text); border-color: var(--accent); background: rgba(74,158,255,0.10); }
  .chip.reset { color: var(--subtle); margin-left: auto; }
  .chip.reset:hover { color: var(--text); }
  .counter { font-size: 11px; color: var(--muted); margin-top: 8px; }
  .empty { text-align: center; padding: 40px 0; font-size: 13px; }
</style>
</head>
<body>
<h1>trail-snow v2 report</h1>
<div class="sub">SNODAS-sampled snow depth along trail geometry. SNODAS day: __GRIDDATE__. Generated __DATE__.</div>
<div class="controls">
  <input type="search" id="q" placeholder="Search trail, area, or keyword (e.g. 'pass', 'lake', 'glacier')..." autocomplete="off">
  <div class="chiprow">
    <div class="chipgroup" data-group="status">
      <button class="chip status-chip active" data-status="snowy">snowed in</button>
      <button class="chip status-chip active" data-status="patchy">patchy</button>
      <button class="chip status-chip active" data-status="open">open</button>
      <button class="chip status-chip active" data-status="unknown">unknown</button>
    </div>
    <div class="chipgroup" data-group="state">__STATECHIPS__</div>
    <button class="chip reset" id="reset">reset</button>
  </div>
  <div class="counter"><span id="visible">__TOTAL__</span> of __TOTAL__ trails</div>
</div>
<div class="summary">__SUMMARY__</div>
<div id="trails">__BODY__</div>
<div id="empty" class="empty muted" hidden>No trails match your filters.</div>
<footer>
  Status thresholds: <b>snowed in</b> = at least 60% of sampled trail points have &ge; __THRESHOLD__ cm of snow depth;
  <b>partly snowy</b> = 20 to 60%; <b>likely open</b> = under 20%.<br>
  Data: SNODAS daily 1 km masked CONUS grid from NSIDC G02158 + OSM via Overpass + USGS 3DEP elevation.<br>
  This is an estimate at SNODAS resolution (~1 km), not a verdict.<br>
  <b>Access</b> badge combines: (1) live USFS road status (open vs. closed-to-motorized-use feature layers from EDW), and (2) SNODAS snow depth at the lowest sampled trail point. Maintained passenger-car roads are treated as drivable even when SNODAS shows snow (Paradise, Hwy 20 once plowed). The closed-roads layer overrides everything else. Without an FS road match, we fall back to the SNODAS proxy.
</footer>
<script>
(function() {
  const q = document.getElementById('q');
  const reset = document.getElementById('reset');
  const trails = document.querySelectorAll('#trails .trail');
  const counter = document.getElementById('visible');
  const empty = document.getElementById('empty');
  const statusChips = document.querySelectorAll('.status-chip');
  const stateChips = document.querySelectorAll('.state-chip');

  function activeSet(chips, attr) {
    const s = new Set();
    chips.forEach(c => { if (c.classList.contains('active')) s.add(c.dataset[attr]); });
    return s;
  }

  function apply() {
    const term = (q.value || '').trim().toLowerCase();
    const statuses = activeSet(statusChips, 'status');
    const states = activeSet(stateChips, 'state');
    let visible = 0;
    trails.forEach(t => {
      const blob = t.dataset.search || '';
      const okSearch = !term || blob.includes(term);
      const okStatus = statuses.has(t.dataset.status);
      const okState = states.has(t.dataset.state);
      const show = okSearch && okStatus && okState;
      t.style.display = show ? '' : 'none';
      if (show) visible++;
    });
    counter.textContent = visible;
    empty.hidden = visible !== 0;
  }

  q.addEventListener('input', apply);
  [...statusChips, ...stateChips].forEach(c => {
    c.addEventListener('click', () => { c.classList.toggle('active'); apply(); });
  });
  reset.addEventListener('click', () => {
    q.value = '';
    [...statusChips, ...stateChips].forEach(c => c.classList.add('active'));
    apply();
  });
})();
</script>
</body>
</html>
"""
