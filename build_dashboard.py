#!/usr/bin/env python3
"""Build dashboard.html from garmin/data.json -- weekly training + recovery trends."""

import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_PATH = HERE / "garmin" / "data.json"
OUT_PATH = HERE / "dashboard.html"

METERS_PER_MILE = 1609.344
METERS_PER_FOOT = 0.3048


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())  # Monday


def load_data() -> dict:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def bucket_weeks(data: dict):
    wellness = data.get("wellness", {})
    activities = list(data.get("activities", {}).values())

    all_dates = list(wellness.keys()) + [a["date"] for a in activities if a.get("date")]
    if not all_dates:
        return []

    parsed = [datetime.strptime(d, "%Y-%m-%d").date() for d in all_dates]
    first_week = week_start(min(parsed))
    last_week = week_start(max(parsed))

    weeks = []
    w = first_week
    while w <= last_week:
        weeks.append(w)
        w += timedelta(days=7)

    by_week_wellness = defaultdict(list)
    for iso, w in wellness.items():
        d = datetime.strptime(iso, "%Y-%m-%d").date()
        by_week_wellness[week_start(d)].append(w)

    by_week_activities = defaultdict(list)
    for a in activities:
        if not a.get("date"):
            continue
        d = datetime.strptime(a["date"], "%Y-%m-%d").date()
        by_week_activities[week_start(d)].append(a)

    result = []
    today = date.today()
    for w in weeks:
        wel = by_week_wellness.get(w, [])
        acts = by_week_activities.get(w, [])

        distance_m = sum(a.get("distance_m") or 0 for a in acts)
        elevation_m = sum(a.get("elevation_gain_m") or 0 for a in acts)

        hr_weighted, hr_duration = 0.0, 0.0
        for a in acts:
            if a.get("avg_hr") and a.get("duration_s"):
                hr_weighted += a["avg_hr"] * a["duration_s"]
                hr_duration += a["duration_s"]
        avg_hr = (hr_weighted / hr_duration) if hr_duration else None

        def avg(field):
            vals = [x[field] for x in wel if x.get(field) is not None]
            return (sum(vals) / len(vals)) if vals else None

        result.append({
            "week_start": w.isoformat(),
            "is_current": w == week_start(today),
            "volume_mi": distance_m / METERS_PER_MILE,
            "vert_ft": elevation_m / METERS_PER_FOOT,
            "avg_hr": avg_hr,
            "sleep_h": avg("sleep_hours"),
            "hrv_ms": avg("hrv_overnight"),
            "readiness": avg("training_readiness"),
            "n_activities": len(acts),
            "n_days_logged": len(wel),
        })
    return result


MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def week_label(iso: str) -> str:
    d = datetime.strptime(iso, "%Y-%m-%d").date()
    return f"{MONTH_ABBR[d.month - 1]} {d.day}"


def fmt(v, decimals=0, suffix=""):
    if v is None:
        return "–"
    return f"{v:,.{decimals}f}{suffix}"


def delta_badge(cur, prev, higher_is_better=True, decimals=0):
    if cur is None or prev is None or prev == 0:
        return ""
    diff = cur - prev
    pct = (diff / abs(prev)) * 100
    if abs(pct) < 1:
        return '<span class="delta flat">flat</span>'
    up = diff > 0
    good = up if higher_is_better else not up
    cls = "good" if good else "bad"
    arrow = "↑" if up else "↓"
    return f'<span class="delta {cls}">{arrow} {abs(pct):.0f}%</span>'


def sparkline(values, weeks, color, unit="", decimals=0, kind="line"):
    """Render a compact SVG trend chart. `values` may contain None."""
    W, H = 280, 84
    pad_l, pad_r, pad_t, pad_b = 8, 8, 10, 18
    plot_w = W - pad_l - pad_r
    plot_h = H - pad_t - pad_b

    pts = [(i, v) for i, v in enumerate(values) if v is not None]
    if len(pts) < 2:
        return f'<svg viewBox="0 0 {W} {H}" class="spark"><text x="{W/2}" y="{H/2}" class="spark-empty" text-anchor="middle">Not enough data yet</text></svg>'

    vmin = min(v for _, v in pts)
    vmax = max(v for _, v in pts)
    if vmax == vmin:
        vmax = vmin + 1

    def x_of(i):
        return pad_l + (i / (len(values) - 1)) * plot_w if len(values) > 1 else pad_l

    def y_of(v):
        return pad_t + plot_h - ((v - vmin) / (vmax - vmin)) * plot_h

    baseline_y = pad_t + plot_h

    svg = [f'<svg viewBox="0 0 {W} {H}" class="spark" role="img">']
    svg.append(f'<line x1="{pad_l}" y1="{baseline_y}" x2="{W - pad_r}" y2="{baseline_y}" class="spark-grid" />')

    if kind == "bar":
        bar_w = plot_w / len(values) * 0.55
        for i, v in enumerate(values):
            if v is None:
                continue
            x = x_of(i) - bar_w / 2
            y = y_of(v)
            h = baseline_y - y
            last = (i == len(values) - 1)
            cls = "bar-current" if last else "bar"
            svg.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{h:.1f}" rx="2" class="{cls}"><title>{week_label(weeks[i])}: {fmt(v, decimals)}{unit}</title></rect>')
    else:
        path_pts = [(x_of(i), y_of(v)) for i, v in pts]
        line_d = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in path_pts)
        area_d = line_d + f" L {path_pts[-1][0]:.1f} {baseline_y} L {path_pts[0][0]:.1f} {baseline_y} Z"
        svg.append(f'<path d="{area_d}" class="spark-area" />')
        svg.append(f'<path d="{line_d}" class="spark-line" />')
        for idx, (i, v) in enumerate(pts):
            x, y = path_pts[idx]
            last = (i == len(values) - 1)
            r = 3.5 if last else 2
            cls = "dot-current" if last else "dot"
            svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" class="{cls}"><title>{week_label(weeks[i])}: {fmt(v, decimals)}{unit}</title></circle>')

    first_i = pts[0][0]
    last_i = pts[-1][0]
    svg.append(f'<text x="{x_of(first_i):.1f}" y="{H - 4}" class="spark-tick" text-anchor="start">{week_label(weeks[first_i])}</text>')
    svg.append(f'<text x="{x_of(last_i):.1f}" y="{H - 4}" class="spark-tick" text-anchor="end">{week_label(weeks[last_i])}</text>')

    svg.append("</svg>")
    return "".join(svg)


def metric_card(title, unit_label, weeks_iso, values, decimals, color_var, higher_is_better, kind, current_is_partial):
    cur = values[-1] if values else None
    prev = values[-2] if len(values) > 1 else None
    if current_is_partial:
        badge = '<span class="delta flat">so far</span>'
    else:
        badge = delta_badge(cur, prev, higher_is_better, decimals)
    chart = sparkline(values, weeks_iso, color_var, "", decimals, kind)
    big = fmt(cur, decimals)
    return f'''
    <div class="card">
      <div class="card-head">
        <span class="card-title">{title}</span>
        {badge}
      </div>
      <div class="card-value">{big}<span class="card-unit">{unit_label}</span></div>
      {chart}
    </div>'''


def build_html(weeks: list) -> str:
    if not weeks:
        weeks = []

    weeks_iso = [w["week_start"] for w in weeks]
    volume = [w["volume_mi"] for w in weeks]
    vert = [w["vert_ft"] for w in weeks]
    hr = [w["avg_hr"] for w in weeks]
    sleep = [w["sleep_h"] for w in weeks]
    hrv = [w["hrv_ms"] for w in weeks]
    readiness = [w["readiness"] for w in weeks]

    cur = weeks[-1] if weeks else {}
    is_partial = bool(cur.get("is_current"))
    now = datetime.now()
    hour_12 = now.hour % 12 or 12
    generated = f"{now.strftime('%A')}, {MONTH_ABBR[now.month - 1]} {now.day}, {now.year} - {hour_12}:{now.strftime('%M %p')}"

    training_cards = "".join([
        metric_card("Weekly Volume", "mi", weeks_iso, volume, 1, "--training", True, "bar", is_partial),
        metric_card("Total Vert", "ft", weeks_iso, vert, 0, "--training", True, "bar", is_partial),
        metric_card("Avg Heart Rate", "bpm", weeks_iso, hr, 0, "--training", False, "line", is_partial),
    ])
    recovery_cards = "".join([
        metric_card("Sleep", "h", weeks_iso, sleep, 1, "--recovery", True, "line", is_partial),
        metric_card("HRV", "ms", weeks_iso, hrv, 0, "--recovery", True, "line", is_partial),
        metric_card("Training Readiness", "", weeks_iso, readiness, 0, "--recovery", True, "line", is_partial),
    ])

    week_note = ""
    if cur:
        partial_str = " (in progress)" if is_partial else ""
        week_note = f'Week of {week_label(cur["week_start"])}{partial_str} – {cur.get("n_activities", 0)} activities logged, {cur.get("n_days_logged", 0)} days of wellness data'

    return (
        HTML_TEMPLATE
        .replace("{{generated}}", generated)
        .replace("{{week_note}}", week_note)
        .replace("{{training_cards}}", training_cards)
        .replace("{{recovery_cards}}", recovery_cards)
    )


CSS = """
<style>
  :root {
    --bg: #eef2f1;
    --surface: #ffffff;
    --surface-2: #f5f8f7;
    --ink: #1a1f1e;
    --ink-muted: #5c6664;
    --border: #dde3e1;
    --training: #c1652b;
    --training-soft: rgba(193, 101, 43, 0.14);
    --recovery: #03948a;
    --recovery-soft: rgba(3, 148, 138, 0.14);
    --good: #1f7a4c;
    --bad: #b23b2e;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #141a19;
      --surface: #1c2422;
      --surface-2: #202a28;
      --ink: #edefee;
      --ink-muted: #9bb0ab;
      --border: #2b3432;
      --training: #cc7038;
      --training-soft: rgba(204, 112, 56, 0.16);
      --recovery: #1f9e96;
      --recovery-soft: rgba(31, 158, 150, 0.16);
      --good: #4fbf82;
      --bad: #e2685a;
    }
  }
  :root[data-theme="dark"] {
    --bg: #141a19;
    --surface: #1c2422;
    --surface-2: #202a28;
    --ink: #edefee;
    --ink-muted: #9bb0ab;
    --border: #2b3432;
    --training: #cc7038;
    --training-soft: rgba(204, 112, 56, 0.16);
    --recovery: #1f9e96;
    --recovery-soft: rgba(31, 158, 150, 0.16);
    --good: #4fbf82;
    --bad: #e2685a;
  }
  :root[data-theme="light"] {
    --bg: #eef2f1;
    --surface: #ffffff;
    --surface-2: #f5f8f7;
    --ink: #1a1f1e;
    --ink-muted: #5c6664;
    --border: #dde3e1;
    --training: #c1652b;
    --training-soft: rgba(193, 101, 43, 0.14);
    --recovery: #03948a;
    --recovery-soft: rgba(3, 148, 138, 0.14);
    --good: #1f7a4c;
    --bad: #b23b2e;
  }

  * { box-sizing: border-box; }

  .dashboard {
    background: var(--bg);
    color: var(--ink);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    padding: 28px clamp(16px, 4vw, 40px) 40px;
    max-width: 1180px;
    margin: 0 auto;
  }

  .topbar {
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    flex-wrap: wrap;
    gap: 12px;
    border-bottom: 1px solid var(--border);
    padding-bottom: 18px;
    margin-bottom: 28px;
  }
  .topbar h1 {
    font-family: Georgia, "Iowan Old Style", "Times New Roman", serif;
    font-size: clamp(24px, 3.4vw, 32px);
    font-weight: 600;
    margin: 0 0 4px;
    letter-spacing: -0.01em;
  }
  .subtitle { margin: 0; color: var(--ink-muted); font-size: 14px; }
  .topbar-meta {
    text-align: right;
    font-size: 12px;
    color: var(--ink-muted);
    line-height: 1.5;
  }
  .topbar-meta strong {
    color: var(--ink);
    font-family: ui-monospace, "Cascadia Code", "SF Mono", Consolas, monospace;
    font-size: 13px;
    font-weight: 500;
  }

  .columns {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 28px;
  }
  @media (max-width: 720px) {
    .columns { grid-template-columns: 1fr; }
  }

  .side h2 {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--ink-muted);
    margin: 0 0 14px;
  }
  .side-dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
  .dot-training { background: var(--training); }
  .dot-recovery { background: var(--recovery); }

  .card-grid { display: flex; flex-direction: column; gap: 14px; }

  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px 18px 12px;
  }
  .side-training .card { border-left: 3px solid var(--training); }
  .side-recovery .card { border-left: 3px solid var(--recovery); }

  .card-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 6px;
  }
  .card-title {
    font-size: 12.5px;
    font-weight: 600;
    color: var(--ink-muted);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .delta {
    font-size: 11.5px;
    font-weight: 600;
    padding: 2px 7px;
    border-radius: 20px;
    background: var(--surface-2);
    color: var(--ink-muted);
  }
  .delta.good { color: var(--good); background: color-mix(in srgb, var(--good) 14%, transparent); }
  .delta.bad { color: var(--bad); background: color-mix(in srgb, var(--bad) 14%, transparent); }
  .delta.flat { color: var(--ink-muted); }

  .card-value {
    font-family: ui-monospace, "Cascadia Code", "SF Mono", Consolas, monospace;
    font-size: 28px;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    margin-bottom: 6px;
  }
  .card-unit {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 13px;
    font-weight: 500;
    color: var(--ink-muted);
    margin-left: 4px;
  }

  .spark { width: 100%; height: auto; display: block; overflow: visible; }
  .spark-grid { stroke: var(--border); stroke-width: 1; }
  .spark-tick { font-size: 9px; fill: var(--ink-muted); }
  .spark-empty { font-size: 11px; fill: var(--ink-muted); }

  .side-training .spark-line { stroke: var(--training); stroke-width: 2; fill: none; }
  .side-training .spark-area { fill: var(--training-soft); stroke: none; }
  .side-training .dot { fill: var(--training); opacity: 0.55; }
  .side-training .dot-current { fill: var(--training); }
  .side-training .bar { fill: var(--training); opacity: 0.45; }
  .side-training .bar-current { fill: var(--training); }

  .side-recovery .spark-line { stroke: var(--recovery); stroke-width: 2; fill: none; }
  .side-recovery .spark-area { fill: var(--recovery-soft); stroke: none; }
  .side-recovery .dot { fill: var(--recovery); opacity: 0.55; }
  .side-recovery .dot-current { fill: var(--recovery); }
  .side-recovery .bar { fill: var(--recovery); opacity: 0.45; }
  .side-recovery .bar-current { fill: var(--recovery); }

  .foot {
    margin-top: 32px;
    text-align: center;
    font-size: 12px;
    color: var(--ink-muted);
  }
</style>
"""

HTML_TEMPLATE = "<title>Training Dashboard</title>" + CSS + """<div class="dashboard">
  <header class="topbar">
    <div class="topbar-title">
      <h1>Training Dashboard</h1>
      <p class="subtitle">{{week_note}}</p>
    </div>
    <div class="topbar-meta">Last updated<br><strong>{{generated}}</strong></div>
  </header>

  <div class="columns">
    <section class="side side-training">
      <h2><span class="side-dot dot-training"></span>Training</h2>
      <div class="card-grid">
        {{training_cards}}
      </div>
    </section>

    <section class="side side-recovery">
      <h2><span class="side-dot dot-recovery"></span>Recovery</h2>
      <div class="card-grid">
        {{recovery_cards}}
      </div>
    </section>
  </div>

  <footer class="foot">Built from your Garmin data - say "update my dashboard" to refresh</footer>
</div>
"""


def main():
    data = load_data()
    weeks = bucket_weeks(data)
    body = build_html(weeks)
    out_path = HERE / "dashboard.html"
    out_path.write_text(body, encoding="utf-8")
    print(f"Aggregated {len(weeks)} weeks. Dashboard written to {out_path}")


if __name__ == "__main__":
    main()
