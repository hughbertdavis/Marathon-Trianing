#!/usr/bin/env python3
"""Build the multi-page docs/ site from garmin/data.json.

Pages: index (menu + race countdown), training, recovery, altitude, lifetime.
Clicking any point on a weekly chart switches every card (and race predictor /
activity list, on the training page) on that page to that week.
"""

import json
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_PATH = HERE / "garmin" / "data.json"
OUT_PATH = HERE / "docs" / "index.html"  # OUT_PATH.parent is the docs/ output dir

METERS_PER_MILE = 1609.344
METERS_PER_FOOT = 0.3048

MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())  # Monday


def week_label(d: date) -> str:
    return f"{MONTH_ABBR[d.month - 1]} {d.day} '{str(d.year)[2:]}"


def load_data() -> dict:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def grade_adjusted_pace(pace_s_per_mi, distance_m, elevation_gain_m):
    """Approximate GAP: normalizes uphill effort to an equivalent flat-ground pace.

    Rule of thumb (~3.3% pace cost per 1% average grade), using net gain over
    distance as the average grade since per-segment grade data isn't available.
    """
    if not pace_s_per_mi or not distance_m or not elevation_gain_m:
        return pace_s_per_mi
    grade_pct = (elevation_gain_m / distance_m) * 100
    factor = 1 + 0.033 * grade_pct
    return pace_s_per_mi / factor if factor > 0 else pace_s_per_mi


def activity_summary(a: dict) -> dict:
    distance_m = a.get("distance_m")
    duration_s = a.get("duration_s")
    elevation_gain_m = a.get("elevation_gain_m")
    pace_s_per_mi = None
    if distance_m and duration_s:
        miles = distance_m / METERS_PER_MILE
        if miles > 0:
            pace_s_per_mi = duration_s / miles

    avg_elevation_m = a.get("avg_elevation_m")

    return {
        "name": a.get("name") or "Activity",
        "type": a.get("type") or "activity",
        "date": a.get("date"),
        "start_local": a.get("start_local"),
        "distance_mi": (distance_m / METERS_PER_MILE) if distance_m else None,
        "duration_s": duration_s,
        "elevation_ft": (elevation_gain_m / METERS_PER_FOOT) if elevation_gain_m else None,
        "avg_elevation_ft": (avg_elevation_m / METERS_PER_FOOT) if avg_elevation_m is not None else None,
        "avg_hr": a.get("avg_hr"),
        "calories": a.get("calories"),
        "pace_s_per_mi": pace_s_per_mi,
        "gap_s_per_mi": grade_adjusted_pace(pace_s_per_mi, distance_m, elevation_gain_m),
    }


def bucket_weeks(data: dict) -> list:
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
    for iso, wel in wellness.items():
        d = datetime.strptime(iso, "%Y-%m-%d").date()
        by_week_wellness[week_start(d)].append(wel)

    by_week_activities = defaultdict(list)
    for a in activities:
        if not a.get("date"):
            continue
        d = datetime.strptime(a["date"], "%Y-%m-%d").date()
        by_week_activities[week_start(d)].append(a)

    def avg(items, field):
        vals = [x[field] for x in items if x.get(field) is not None]
        return (sum(vals) / len(vals)) if vals else None

    def latest(items, field):
        ordered = sorted(items, key=lambda x: x.get("date") or "")
        for x in reversed(ordered):
            if x.get(field) is not None:
                return x[field]
        return None

    result = []
    today = date.today()
    for w in weeks:
        wel = by_week_wellness.get(w, [])
        acts = sorted(by_week_activities.get(w, []), key=lambda a: a.get("start_local") or "")

        distance_m = sum(a.get("distance_m") or 0 for a in acts)
        elevation_m = sum(a.get("elevation_gain_m") or 0 for a in acts)

        hr_weighted, hr_duration = 0.0, 0.0
        for a in acts:
            if a.get("avg_hr") and a.get("duration_s"):
                hr_weighted += a["avg_hr"] * a["duration_s"]
                hr_duration += a["duration_s"]
        avg_hr = (hr_weighted / hr_duration) if hr_duration else None

        result.append({
            "week_start": w.isoformat(),
            "week_label": week_label(w),
            "is_current": w == week_start(today),
            "volume_mi": distance_m / METERS_PER_MILE,
            "vert_ft": elevation_m / METERS_PER_FOOT,
            "avg_hr": avg_hr,
            "vo2max": avg(wel, "vo2max"),
            "sleep_h": avg(wel, "sleep_hours"),
            "hrv_ms": avg(wel, "hrv_overnight"),
            "readiness": avg(wel, "training_readiness"),
            "race_5k": avg(wel, "race_5k_s"),
            "race_10k": avg(wel, "race_10k_s"),
            "race_half": avg(wel, "race_half_s"),
            "race_marathon": avg(wel, "race_marathon_s"),
            "training_status": latest(wel, "training_status"),
            "acwr_ratio": avg(wel, "acwr_ratio"),
            "acwr_status": latest(wel, "acwr_status"),
            "fitness_age": latest(wel, "fitness_age"),
            "resting_hr": avg(wel, "resting_hr"),
            "body_battery_low": avg(wel, "body_battery_low"),
            "body_battery_high": avg(wel, "body_battery_high"),
            "deep_sleep_h": avg(wel, "deep_sleep_h"),
            "light_sleep_h": avg(wel, "light_sleep_h"),
            "rem_sleep_h": avg(wel, "rem_sleep_h"),
            "awake_h": avg(wel, "awake_h"),
            "nap_minutes": avg(wel, "nap_minutes"),
            "avg_spo2": avg(wel, "avg_spo2"),
            "avg_respiration": avg(wel, "avg_respiration"),
            "heat_altitude_acclimation": latest(wel, "heat_altitude_acclimation"),
            "n_activities": len(acts),
            "n_days_logged": len(wel),
            "activities": [activity_summary(a) for a in acts],
        })
    return result


PR_BUCKETS = [
    ("5K", 4800, 5300),
    ("10K", 9600, 10600),
    ("Half Marathon", 20600, 21700),
    ("Marathon", 41500, 42800),
]


def compute_personal_records(data: dict) -> dict:
    activities = list(data.get("activities", {}).values())

    records = {}
    for label, lo, hi in PR_BUCKETS:
        candidates = [a for a in activities if a.get("distance_m") and lo <= a["distance_m"] <= hi and a.get("duration_s")]
        if candidates:
            best = min(candidates, key=lambda a: a["duration_s"])
            records[label] = {"duration_s": best["duration_s"], "date": best.get("date"), "name": best.get("name")}
        else:
            records[label] = None

    longest = max(
        (a for a in activities if a.get("distance_m")),
        key=lambda a: a["distance_m"],
        default=None,
    )
    most_vert = max(
        (a for a in activities if a.get("elevation_gain_m")),
        key=lambda a: a["elevation_gain_m"],
        default=None,
    )

    return {
        "races": records,
        "longest_run": {
            "distance_mi": longest["distance_m"] / METERS_PER_MILE,
            "date": longest.get("date"),
            "name": longest.get("name"),
        } if longest else None,
        "most_vert": {
            "elevation_ft": most_vert["elevation_gain_m"] / METERS_PER_FOOT,
            "date": most_vert.get("date"),
            "name": most_vert.get("name"),
        } if most_vert else None,
    }


def compute_streaks(data: dict) -> dict:
    activities = list(data.get("activities", {}).values())
    active_days = sorted({a["date"] for a in activities if a.get("date")})
    if not active_days:
        return {"current": 0, "best": 0}

    parsed = [datetime.strptime(d, "%Y-%m-%d").date() for d in active_days]
    day_set = set(parsed)

    best = 1
    run = 1
    for i in range(1, len(parsed)):
        if (parsed[i] - parsed[i - 1]).days == 1:
            run += 1
            best = max(best, run)
        else:
            run = 1

    today = date.today()
    current = 0
    cursor = today
    if cursor not in day_set:
        cursor -= timedelta(days=1)
    while cursor in day_set:
        current += 1
        cursor -= timedelta(days=1)

    return {"current": current, "best": best}


def compute_heatmap(data: dict) -> list:
    activities = list(data.get("activities", {}).values())
    by_day = defaultdict(float)
    for a in activities:
        if a.get("date") and a.get("distance_m"):
            by_day[a["date"]] += a["distance_m"] / METERS_PER_MILE

    if not by_day:
        return []

    all_days = sorted(by_day.keys())
    start = datetime.strptime(all_days[0], "%Y-%m-%d").date()
    start = start - timedelta(days=start.weekday())  # align to Monday
    end = date.today()

    days = []
    d = start
    while d <= end:
        iso = d.isoformat()
        days.append({"date": iso, "miles": round(by_day.get(iso, 0.0), 2)})
        d += timedelta(days=1)
    return days


DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def day_label(d: date) -> str:
    return f"{DAY_NAMES[d.weekday()]}, {MONTH_ABBR[d.month - 1]} {d.day}, {d.year}"


def compute_daily_days(data: dict, days_back: int = 90) -> list:
    wellness = data.get("wellness", {})
    activities = list(data.get("activities", {}).values())
    by_day_activities = defaultdict(list)
    for a in activities:
        if a.get("date"):
            by_day_activities[a["date"]].append(a)

    today = date.today()
    start = today - timedelta(days=days_back - 1)

    result = []
    d = start
    while d <= today:
        iso = d.isoformat()
        acts = sorted(by_day_activities.get(iso, []), key=lambda a: a.get("start_local") or "")
        result.append({
            "date": iso,
            "date_label": day_label(d),
            "wellness": wellness.get(iso) or {},
            "activities": [activity_summary(a) for a in acts],
        })
        d += timedelta(days=1)
    return result


def weekly_stress_series(data: dict) -> list:
    profile = data.get("profile", {}) or {}
    weekly = profile.get("weekly_stress") or {}
    rows = sorted(weekly.items(), key=lambda kv: kv[0])
    return [{"date": d, "value": v} for d, v in rows if v is not None]


ACTIVITY_TYPE_LABELS = {
    "running": "Running", "cycling": "Cycling", "hiking": "Hiking",
    "swimming": "Swimming", "other": "Other",
}


ELEVATION_BANDS = [
    ("Low (< 6,500 ft)", 0, 1981),
    ("Moderate (6,500-9,000 ft)", 1981, 2743),
    ("High (9,000-11,500 ft)", 2743, 3505),
    ("Very High (11,500+ ft)", 3505, 999999),
]


def compute_altitude_stats(data: dict) -> dict:
    """Our own altitude-adaptation estimate, since Garmin's own score is unavailable
    for this account. Uses real elevation (min/max/avg per activity, from Garmin's
    raw activity data) plus pace/HR to approximate acclimation -- there's no ambient
    temperature data available, so this is elevation-based only, not heat-based."""
    activities = list(data.get("activities", {}).values())
    today = date.today()
    cutoff_90d = (today - timedelta(days=90)).isoformat()

    with_elev = [a for a in activities if a.get("avg_elevation_m") is not None]
    # Pace/HR efficiency is only comparable within one activity type -- mixing in
    # hiking (much slower pace, different HR profile) would make "high altitude"
    # look artificially different since hikes happen to occur at higher elevation.
    running_with_elev = [a for a in with_elev if "running" in (a.get("type") or "").lower()]

    bands = []
    for label, lo, hi in ELEVATION_BANDS:
        in_band = [
            a for a in running_with_elev
            if lo <= a["avg_elevation_m"] < hi and a.get("distance_m") and a.get("duration_s") and a.get("avg_hr")
        ]
        if not in_band:
            bands.append({"label": label, "count": 0})
            continue

        paces = []
        effs = []
        hr_sum = 0.0
        for a in in_band:
            miles = a["distance_m"] / METERS_PER_MILE
            pace_s = a["duration_s"] / miles if miles > 0 else None
            mph = 3600 / pace_s if pace_s else None
            eff = a["avg_hr"] / mph if mph else None
            if pace_s:
                paces.append(pace_s)
            if eff:
                effs.append(eff)
            hr_sum += a["avg_hr"]

        bands.append({
            "label": label,
            "count": len(in_band),
            "avg_pace_s_per_mi": sum(paces) / len(paces) if paces else None,
            "avg_hr": hr_sum / len(in_band),
            "efficiency": sum(effs) / len(effs) if effs else None,
        })

    # Chronological efficiency trend for moderate-and-up exposures, to see whether
    # HR cost per mph at altitude is trending down (adapting) over repeated exposure.
    moderate_plus = sorted(
        (a for a in running_with_elev if a["avg_elevation_m"] >= 1981 and a.get("distance_m") and a.get("duration_s") and a.get("avg_hr")),
        key=lambda a: a.get("date") or "",
    )
    efficiency_series = []
    for a in moderate_plus:
        miles = a["distance_m"] / METERS_PER_MILE
        if miles <= 0:
            continue
        pace_s = a["duration_s"] / miles
        mph = 3600 / pace_s
        efficiency_series.append({
            "date": a["date"],
            "efficiency": a["avg_hr"] / mph,
            "elevation_ft": a["avg_elevation_m"] / METERS_PER_FOOT,
        })

    recent = [a for a in with_elev if a.get("date") and a["date"] >= cutoff_90d]
    max_elev = max((a["max_elevation_m"] for a in with_elev if a.get("max_elevation_m") is not None), default=None)

    return {
        "bands": bands,
        "efficiency_series": efficiency_series,
        "max_elevation_ft": (max_elev / METERS_PER_FOOT) if max_elev else None,
        "avg_elevation_ft_90d": (
            sum(a["avg_elevation_m"] for a in recent) / len(recent) / METERS_PER_FOOT
        ) if recent else None,
        "high_alt_count_90d": sum(1 for a in recent if a["avg_elevation_m"] >= 2743),
        "activities_with_elevation": len(with_elev),
    }


def compute_lifetime_stats(data: dict) -> dict:
    activities = list(data.get("activities", {}).values())
    profile = data.get("profile", {}) or {}

    total_distance_mi = sum((a.get("distance_m") or 0) for a in activities) / METERS_PER_MILE
    total_vert_ft = sum((a.get("elevation_gain_m") or 0) for a in activities) / METERS_PER_FOOT
    total_duration_s = sum((a.get("duration_s") or 0) for a in activities)

    by_type = defaultdict(lambda: {"count": 0, "distance_mi": 0.0})
    for a in activities:
        t = (a.get("type") or "other").lower()
        by_type[t]["count"] += 1
        by_type[t]["distance_mi"] += (a.get("distance_m") or 0) / METERS_PER_MILE

    types = [
        {"type": ACTIVITY_TYPE_LABELS.get(t, t.replace("_", " ").title()), "count": v["count"], "distance_mi": v["distance_mi"]}
        for t, v in sorted(by_type.items(), key=lambda kv: -kv[1]["count"])
    ]

    dates = sorted(a["date"] for a in activities if a.get("date"))

    return {
        "lifetime_activity_count": profile.get("lifetime_activity_count"),
        "synced_activity_count": len(activities),
        "total_distance_mi": total_distance_mi,
        "total_vert_ft": total_vert_ft,
        "total_duration_s": total_duration_s,
        "by_type": types,
        "earliest_synced": dates[0] if dates else None,
        "latest_synced": dates[-1] if dates else None,
    }


def fmt(v, decimals=0):
    if v is None:
        return "–"
    return f"{v:,.{decimals}f}"


def fmt_race(seconds):
    if seconds is None:
        return "–"
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_pace(seconds_per_mile):
    if not seconds_per_mile:
        return "–"
    m, s = divmod(round(seconds_per_mile), 60)
    return f"{m}:{s:02d}/mi"


STATUS_LABELS = {
    "PEAKING": ("Peaking", "good"),
    "PRODUCTIVE": ("Productive", "good"),
    "MAINTAINING": ("Maintaining", "good"),
    "RECOVERY": ("Recovery", "info"),
    "OVERREACHING": ("Overreaching", "warn"),
    "UNPRODUCTIVE": ("Unproductive", "warn"),
    "DETRAINING": ("Detraining", "warn"),
    "NO_STATUS": ("No Status", "info"),
}


def status_pill(raw_status):
    if not raw_status:
        return "–", "info"
    # Garmin appends a numeric device-index suffix (e.g. "PEAKING_1") to several
    # status codes, not just RECOVERY_1 -- strip any trailing "_<digits>" before matching.
    key = re.sub(r"_\d+$", "", raw_status.upper())
    if key in STATUS_LABELS:
        return STATUS_LABELS[key]
    label = raw_status.replace("_", " ").title()
    return label, "info"


def acwr_pill(status):
    if not status:
        return "info"
    key = status.upper()
    if key == "HIGH":
        return "bad"
    if key == "LOW":
        return "warn"
    return "good"


def build_race_countdown(weeks: list) -> str:
    goal_path = HERE / "race_goal.json"
    if not goal_path.exists():
        return ""
    goal = json.loads(goal_path.read_text(encoding="utf-8"))

    race_date = datetime.strptime(goal["date"], "%Y-%m-%d").date()
    days_left = (race_date - date.today()).days
    marathon_miles = 26.2188
    goal_pace = goal["goal_seconds"] / marathon_miles

    latest_predicted = None
    for w in reversed(weeks):
        if w.get("race_marathon") is not None:
            latest_predicted = w["race_marathon"]
            break

    delta_html = ""
    if latest_predicted is not None:
        diff = latest_predicted - goal["goal_seconds"]
        if abs(diff) < 30:
            delta_html = '<span class="delta flat">on pace</span>'
        elif diff > 0:
            delta_html = f'<span class="delta bad">{fmt_race(diff)} slower than goal</span>'
        else:
            delta_html = f'<span class="delta good">{fmt_race(abs(diff))} faster than goal</span>'

    when = f"{MONTH_ABBR[race_date.month - 1]} {race_date.day}, {race_date.year}"
    days_label = f"{days_left} days" if days_left >= 0 else "Race day has passed"

    return f'''
  <div class="race-countdown">
    <div class="countdown-main">
      <div class="countdown-days">{days_label}</div>
      <div class="countdown-sub">until {goal['name']} - {when}</div>
    </div>
    <div class="countdown-stats">
      <div class="countdown-stat">
        <div class="stat-label">Goal Time</div>
        <div class="stat-value">{fmt_race(goal['goal_seconds'])}</div>
      </div>
      <div class="countdown-stat">
        <div class="stat-label">Goal Pace</div>
        <div class="stat-value">{fmt_pace(goal_pace)}</div>
      </div>
      <div class="countdown-stat">
        <div class="stat-label">Current Prediction</div>
        <div class="stat-value">{fmt_race(latest_predicted)} {delta_html}</div>
      </div>
    </div>
  </div>'''


def build_personal_records(data: dict) -> str:
    pr = compute_personal_records(data)
    items = []
    for label, _, _ in PR_BUCKETS:
        rec = pr["races"].get(label)
        if rec:
            items.append(f'''
      <div class="pr-item">
        <div class="pr-label">{label}</div>
        <div class="pr-value">{fmt_race(rec["duration_s"])}</div>
        <div class="pr-date">{rec.get("date") or ""}</div>
      </div>''')
    if pr["longest_run"]:
        lr = pr["longest_run"]
        items.append(f'''
      <div class="pr-item">
        <div class="pr-label">Longest Run</div>
        <div class="pr-value">{fmt(lr["distance_mi"], 1)} mi</div>
        <div class="pr-date">{lr.get("date") or ""}</div>
      </div>''')
    if pr["most_vert"]:
        mv = pr["most_vert"]
        items.append(f'''
      <div class="pr-item">
        <div class="pr-label">Most Vert (1 activity)</div>
        <div class="pr-value">{fmt(mv["elevation_ft"], 0)} ft</div>
        <div class="pr-date">{mv.get("date") or ""}</div>
      </div>''')

    if not items:
        return ""
    return f'''
  <div class="pr-panel">
    <h2>Personal Records</h2>
    <div class="pr-grid">{"".join(items)}</div>
  </div>'''


def build_fitness_facts(data: dict, weeks: list) -> str:
    profile = data.get("profile", {}) or {}
    streak = compute_streaks(data)
    cur_week = weeks[-1] if weeks else {}
    status_label, status_cls = status_pill(cur_week.get("training_status"))

    facts = [f'''
      <div class="fact-item">
        <div class="fact-label">Training Status</div>
        <div class="fact-value"><span class="pill pill-{status_cls}">{status_label}</span></div>
      </div>''']

    if profile.get("lactate_threshold_hr"):
        facts.append(f'''
      <div class="fact-item">
        <div class="fact-label">Lactate Threshold</div>
        <div class="fact-value">{profile["lactate_threshold_hr"]} bpm</div>
      </div>''')

    fitness_age = cur_week.get("fitness_age")
    if fitness_age is not None:
        facts.append(f'''
      <div class="fact-item">
        <div class="fact-label">Fitness Age</div>
        <div class="fact-value">{fmt(fitness_age, 0)}</div>
      </div>''')

    facts.append(f'''
      <div class="fact-item">
        <div class="fact-label">Active-Day Streak</div>
        <div class="fact-value">{streak["current"]} days <span class="fact-sub">(best {streak["best"]})</span></div>
      </div>''')


    return f'''
  <div class="fitness-panel">
    <h2>Fitness Facts</h2>
    <div class="fact-grid">{"".join(facts)}</div>
  </div>'''


def build_heatmap(data: dict) -> str:
    days = compute_heatmap(data)
    if not days:
        return ""

    max_miles = max((d["miles"] for d in days), default=0) or 1
    weeks_cols = [days[i:i + 7] for i in range(0, len(days), 7)]

    cells = []
    for week in weeks_cols:
        col = ['<div class="heat-col">']
        for d in week:
            intensity = min(d["miles"] / max_miles, 1.0) if d["miles"] else 0
            level = 0 if intensity == 0 else max(1, min(4, int(intensity * 4) + 1))
            col.append(f'<div class="heat-cell heat-{level}" title="{d["date"]}: {d["miles"]:.1f} mi"></div>')
        col.append("</div>")
        cells.append("".join(col))

    return f'''
  <div class="heatmap-panel">
    <h2>Training Block</h2>
    <div class="heatmap-grid">{"".join(cells)}</div>
  </div>'''


def card_skeleton(slug, title, unit_label):
    """Chart is rendered client-side by buildChart() so it can page through history."""
    return f'''
    <div class="card">
      <div class="card-head">
        <span class="card-title">{title}</span>
        <span class="delta" id="{slug}-badge"></span>
      </div>
      <div class="card-value"><span id="{slug}-value">–</span><span class="card-unit">{unit_label}</span></div>
      <div id="{slug}-chart"></div>
    </div>'''



def static_line_chart(values, labels, decimals=0):
    """Non-interactive trend chart for series on a different date grid than the weekly cards
    (e.g. Garmin's own weekly-stress rollup) -- must not carry 'pt'/data-week, which would
    wrongly trigger the click-to-switch-week handler with a mismatched index."""
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
        svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" class="{cls}"><title>{labels[i]}: {fmt(v, decimals)}</title></circle>')

    svg.append(f'<text x="{path_pts[0][0]:.1f}" y="{H - 4}" class="spark-tick" text-anchor="start">{labels[pts[0][0]]}</text>')
    svg.append(f'<text x="{path_pts[-1][0]:.1f}" y="{H - 4}" class="spark-tick" text-anchor="end">{labels[pts[-1][0]]}</text>')
    svg.append("</svg>")
    return "".join(svg)


def generated_timestamp() -> str:
    now = datetime.now()
    hour_12 = now.hour % 12 or 12
    return f"{now.strftime('%A')}, {MONTH_ABBR[now.month - 1]} {now.day}, {now.year} - {hour_12}:{now.strftime('%M %p')}"


NAV_PAGES = [
    ("index.html", "Overview"),
    ("training.html", "Training"),
    ("recovery.html", "Recovery"),
    ("daily.html", "Daily"),
    ("altitude.html", "Altitude"),
    ("lifetime.html", "Lifetime"),
]


def nav_html(active_file: str) -> str:
    links = []
    for href, label in NAV_PAGES:
        cls = "navlink active" if href == active_file else "navlink"
        links.append(f'<a class="{cls}" href="{href}">{label}</a>')
    return f'<nav class="pagenav">{"".join(links)}</nav>'


PWA_HEAD = '''<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#141a19">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<link rel="manifest" href="manifest.json">
<link rel="icon" href="icons/icon-192.png">
<link rel="apple-touch-icon" href="icons/icon-192.png">
<script>
if ("serviceWorker" in navigator) {
  window.addEventListener("load", function () {
    navigator.serviceWorker.register("sw.js").catch(function () {});
  });
}
</script>'''


def page_shell(active_file: str, title: str, subtitle: str, body_html: str) -> str:
    return f'''{PWA_HEAD}<title>{title} - Training Dashboard</title>{CSS}<div class="dashboard">
  <header class="topbar">
    <div class="topbar-title">
      <h1>Training Dashboard</h1>
      <p class="subtitle">{subtitle}</p>
    </div>
    <div class="topbar-meta">Last updated<br><strong>{generated_timestamp()}</strong></div>
  </header>
  {nav_html(active_file)}
  {body_html}
  <footer class="foot">Built from your Garmin data - say "update my dashboard" to refresh.</footer>
</div>'''


def render_index(data: dict, weeks: list) -> str:
    menu_cards = "".join(
        f'''
    <a class="menu-card" href="{href}">
      <div class="menu-title">{label}</div>
      <div class="menu-desc">{desc}</div>
    </a>'''
        for href, label, desc in [
            ("training.html", "Training", "Weekly volume, vert, HR, VO2 max, ACWR, race predictor, PRs, and activities"),
            ("recovery.html", "Recovery", "Sleep, sleep stages, HRV, resting HR, body battery, stress, naps"),
            ("daily.html", "Daily", "Full detail for one day at a time -- activities, sleep, naps, VO2 max, and more"),
            ("altitude.html", "Altitude", "Our own altitude-adaptation estimate from your elevation and pace/HR data"),
            ("lifetime.html", "Lifetime", "All-time totals across your full Garmin history"),
        ]
    )
    body = f'''
  {build_race_countdown(weeks)}
  <div class="menu-grid">{menu_cards}</div>
  {build_fitness_facts(data, weeks)}'''
    subtitle = weeks[-1]["week_label"] if weeks else ""
    return page_shell("index.html", "Overview", f"Week of {subtitle}" if subtitle else "", body)


def chart_nav_html() -> str:
    return '''
  <div class="chart-nav">
    <button id="chart-earlier" class="navbtn" type="button">&larr; Earlier</button>
    <span id="chart-range" class="chart-range"></span>
    <button id="chart-later" class="navbtn" type="button">Later &rarr;</button>
  </div>'''


def render_script(weeks: list, metrics: list, include_race_predictor: bool, include_activities: bool, extra_js: str = "", include_stage_chart: bool = False) -> str:
    weeks_json = json.dumps(weeks).replace("</", "<\\/")
    metrics_json = json.dumps(metrics)

    race_js = """
    ['5k', '10k', 'half', 'marathon'].forEach(function (k) {
      var el = document.getElementById('race-' + k + '-value');
      if (el) el.textContent = fmtRace(week['race_' + k]);
    });""" if include_race_predictor else ""

    activities_js = """
    var list = document.getElementById('activities-list');
    if (list) {
      if (!week.activities.length) {
        list.innerHTML = '<p class="empty">No activities this week.</p>';
      } else {
        list.innerHTML = week.activities.map(function (act) {
          return '<div class="activity-row">' +
            '<div class="activity-main"><span class="activity-name">' + act.name + '</span>' +
            '<span class="activity-type">' + act.type + '</span></div>' +
            '<div class="activity-stats">' +
            '<span>' + act.date + '</span>' +
            '<span>' + (act.distance_mi != null ? act.distance_mi.toFixed(2) + ' mi' : '–') + '</span>' +
            '<span>' + fmtDuration(act.duration_s) + '</span>' +
            '<span>' + fmtPace(act.pace_s_per_mi) + (act.gap_s_per_mi != null && Math.abs(act.gap_s_per_mi - act.pace_s_per_mi) > 1 ? ' <span class="activity-gap">(GAP ' + fmtPace(act.gap_s_per_mi) + ')</span>' : '') + '</span>' +
            '<span>' + (act.elevation_ft != null ? Math.round(act.elevation_ft) + ' ft' : '–') + '</span>' +
            '<span>' + (act.avg_hr != null ? Math.round(act.avg_hr) + ' bpm' : '–') + '</span>' +
            '</div></div>';
        }).join('');
      }
    }""" if include_activities else ""

    stage_chart_js = """
    var stageEl = document.getElementById('stage-chart');
    if (stageEl) stageEl.innerHTML = buildStageChart();""" if include_stage_chart else ""

    return f"""<script id="weeks-data" type="application/json">{weeks_json}</script>
<script>
(function () {{
  var WEEKS = JSON.parse(document.getElementById('weeks-data').textContent);
  var METRICS = {metrics_json};
  var selected = WEEKS.length - 1;

  function acwrPill(status) {{
    if (!status) return {{ cls: '', text: '' }};
    var key = status.toUpperCase();
    var cls = key === 'HIGH' ? 'bad' : key === 'LOW' ? 'warn' : 'good';
    return {{ cls: cls, text: key.charAt(0) + key.slice(1).toLowerCase() }};
  }}

  function fmtNum(v, decimals) {{
    if (v === null || v === undefined) return '–';
    return Number(v).toLocaleString(undefined, {{ minimumFractionDigits: decimals, maximumFractionDigits: decimals }});
  }}

  function fmtRace(sec) {{
    if (sec === null || sec === undefined) return '–';
    sec = Math.round(sec);
    var h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    var mm = String(m).padStart(2, '0'), ss = String(s).padStart(2, '0');
    return h > 0 ? (h + ':' + mm + ':' + ss) : (m + ':' + ss);
  }}

  function fmtPace(secPerMi) {{
    if (secPerMi === null || secPerMi === undefined || !isFinite(secPerMi)) return '–';
    var m = Math.floor(secPerMi / 60), s = Math.round(secPerMi % 60);
    return m + ':' + String(s).padStart(2, '0') + '/mi';
  }}

  function fmtDuration(s) {{
    if (!s) return '–';
    var h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60);
    return h > 0 ? (h + 'h ' + m + 'm') : (m + 'm');
  }}

  function badgeState(cur, prev, higherBetter, isPartial) {{
    if (isPartial) return {{ cls: 'flat', text: 'so far' }};
    if (cur == null || prev == null || prev === 0) return {{ cls: '', text: '' }};
    var diff = cur - prev;
    var pct = (diff / Math.abs(prev)) * 100;
    if (Math.abs(pct) < 1) return {{ cls: 'flat', text: 'flat' }};
    var up = diff > 0;
    var good = higherBetter ? up : !up;
    var arrow = up ? '↑' : '↓';
    return {{ cls: good ? 'good' : 'bad', text: arrow + ' ' + Math.abs(pct).toFixed(0) + '%' }};
  }}

  var WINDOW_WEEKS = 13;
  var totalPages = Math.max(1, Math.ceil(WEEKS.length / WINDOW_WEEKS));
  var page = 0;

  function windowBounds() {{
    var end = Math.max(0, WEEKS.length - page * WINDOW_WEEKS);
    var start = Math.max(0, end - WINDOW_WEEKS);
    return {{ start: start, end: end }};
  }}

  function buildChart(field, decimals, kind, statusField) {{
    var w = windowBounds();
    var W = 280, H = 84, padL = 8, padR = 8, padT = 10, padB = 18;
    var plotW = W - padL - padR, plotH = H - padT - padB;
    var globalLast = WEEKS.length - 1;
    var n = w.end - w.start;

    var pts = [];
    for (var i = 0; i < n; i++) {{
      var v = WEEKS[w.start + i][field];
      if (v !== null && v !== undefined) pts.push([i, v]);
    }}
    if (pts.length < 2 || n < 2) {{
      return '<svg viewBox="0 0 ' + W + ' ' + H + '" class="spark"><text x="' + (W / 2) + '" y="' + (H / 2) + '" class="spark-empty" text-anchor="middle">Not enough data yet</text></svg>';
    }}

    var vmin = pts[0][1], vmax = pts[0][1];
    pts.forEach(function (p) {{ if (p[1] < vmin) vmin = p[1]; if (p[1] > vmax) vmax = p[1]; }});
    if (vmax === vmin) vmax = vmin + 1;

    function xOf(i) {{ return n > 1 ? padL + (i / (n - 1)) * plotW : padL; }}
    function yOf(v) {{ return padT + plotH - ((v - vmin) / (vmax - vmin)) * plotH; }}
    var baselineY = padT + plotH;
    var svg = ['<svg viewBox="0 0 ' + W + ' ' + H + '" class="spark" role="img">'];
    svg.push('<line x1="' + padL + '" y1="' + baselineY + '" x2="' + (W - padR) + '" y2="' + baselineY + '" class="spark-grid" />');

    function label(i) {{ return WEEKS[w.start + i].week_label; }}
    function valText(v) {{ return fmtNum(v, decimals); }}

    if (kind === 'bar') {{
      var barW = plotW / n * 0.55;
      for (var i = 0; i < n; i++) {{
        var v = WEEKS[w.start + i][field];
        if (v === null || v === undefined) continue;
        var x = xOf(i) - barW / 2, y = yOf(v), h = baselineY - y;
        var isLast = (w.start + i === globalLast);
        var isSel = (w.start + i === selected);
        var cls = 'bar pt' + (isLast ? ' bar-current' : '') + (isSel ? ' selected' : '');
        svg.push('<rect x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + barW.toFixed(1) + '" height="' + h.toFixed(1) + '" rx="2" class="' + cls + '" data-week="' + (w.start + i) + '" tabindex="0"><title>' + label(i) + ': ' + valText(v) + '</title></rect>');
      }}
    }} else {{
      var pathPts = pts.map(function (p) {{ return [xOf(p[0]), yOf(p[1])]; }});
      var lineD = 'M ' + pathPts.map(function (p) {{ return p[0].toFixed(1) + ' ' + p[1].toFixed(1); }}).join(' L ');
      var areaD = lineD + ' L ' + pathPts[pathPts.length - 1][0].toFixed(1) + ' ' + baselineY + ' L ' + pathPts[0][0].toFixed(1) + ' ' + baselineY + ' Z';
      svg.push('<path d="' + areaD + '" class="spark-area" />');
      svg.push('<path d="' + lineD + '" class="spark-line" />');
      for (var idx = 0; idx < pts.length; idx++) {{
        var i = pts[idx][0], v = pts[idx][1];
        var x = pathPts[idx][0], y = pathPts[idx][1];
        var isLast = (w.start + i === globalLast);
        var isSel = (w.start + i === selected);
        var r = isLast ? 3.5 : 2;
        var cls = 'dot pt' + (isLast ? ' dot-current' : '') + (isSel ? ' selected' : '');
        svg.push('<circle cx="' + x.toFixed(1) + '" cy="' + y.toFixed(1) + '" r="' + r + '" class="' + cls + '" data-week="' + (w.start + i) + '" tabindex="0"><title>' + label(i) + ': ' + valText(v) + '</title></circle>');
      }}
    }}

    var firstI = pts[0][0], lastI = pts[pts.length - 1][0];
    svg.push('<text x="' + xOf(firstI).toFixed(1) + '" y="' + (H - 4) + '" class="spark-tick" text-anchor="start">' + label(firstI) + '</text>');
    svg.push('<text x="' + xOf(lastI).toFixed(1) + '" y="' + (H - 4) + '" class="spark-tick" text-anchor="end">' + label(lastI) + '</text>');
    svg.push('</svg>');
    return svg.join('');
  }}

  var SLEEP_STAGES = [['deep', 'deep_sleep_h'], ['light', 'light_sleep_h'], ['rem', 'rem_sleep_h'], ['awake', 'awake_h']];

  function buildStageChart() {{
    var w = windowBounds();
    var W = 280, H = 84, padL = 8, padR = 8, padT = 10, padB = 18;
    var plotW = W - padL - padR, plotH = H - padT - padB;
    var globalLast = WEEKS.length - 1;
    var n = w.end - w.start;

    var totals = [];
    for (var i = 0; i < n; i++) {{
      var wk = WEEKS[w.start + i];
      var t = 0;
      SLEEP_STAGES.forEach(function (p) {{ t += wk[p[1]] || 0; }});
      totals.push(t);
    }}
    var vmax = 0;
    totals.forEach(function (t) {{ if (t > vmax) vmax = t; }});
    if (!vmax || n < 2) {{
      return '<svg viewBox="0 0 ' + W + ' ' + H + '" class="spark"><text x="' + (W / 2) + '" y="' + (H / 2) + '" class="spark-empty" text-anchor="middle">Not enough data yet</text></svg>';
    }}

    var barW = plotW / n * 0.55;
    var baselineY = padT + plotH;
    var svg = ['<svg viewBox="0 0 ' + W + ' ' + H + '" class="spark" role="img">'];
    svg.push('<line x1="' + padL + '" y1="' + baselineY + '" x2="' + (W - padR) + '" y2="' + baselineY + '" class="spark-grid" />');

    for (var i = 0; i < n; i++) {{
      var wk = WEEKS[w.start + i];
      var x = (n > 1 ? padL + (i / (n - 1)) * plotW : padL) - barW / 2;
      var yCursor = baselineY;
      var isSel = (w.start + i === selected);
      var titleBits = SLEEP_STAGES.map(function (p) {{ return p[0] + ' ' + (wk[p[1]] || 0).toFixed(1) + 'h'; }}).join(', ');
      SLEEP_STAGES.forEach(function (p) {{
        var v = wk[p[1]] || 0;
        if (v <= 0) return;
        var segH = (v / vmax) * plotH;
        yCursor -= segH;
        var cls = 'stage-' + p[0] + ' pt' + (isSel ? ' selected' : '');
        svg.push('<rect x="' + x.toFixed(1) + '" y="' + yCursor.toFixed(1) + '" width="' + barW.toFixed(1) + '" height="' + segH.toFixed(1) + '" class="' + cls + '" data-week="' + (w.start + i) + '" tabindex="0"><title>' + WEEKS[w.start + i].week_label + ': ' + titleBits + '</title></rect>');
      }});
    }}

    svg.push('<text x="' + padL + '" y="' + (H - 4) + '" class="spark-tick" text-anchor="start">' + WEEKS[w.start].week_label + '</text>');
    svg.push('<text x="' + (W - padR) + '" y="' + (H - 4) + '" class="spark-tick" text-anchor="end">' + WEEKS[w.end - 1].week_label + '</text>');
    svg.push('</svg>');
    return svg.join('');
  }}

  function renderCharts() {{
    var w = windowBounds();
    METRICS.forEach(function (m) {{
      var el = document.getElementById(m.slug + '-chart');
      if (el) el.innerHTML = buildChart(m.field, m.decimals, m.kind, m.statusField);
    }});
    {stage_chart_js}

    var rangeEl = document.getElementById('chart-range');
    if (rangeEl) rangeEl.textContent = WEEKS[w.start].week_label + ' \\u2013 ' + WEEKS[w.end - 1].week_label;
    var earlierBtn = document.getElementById('chart-earlier');
    var laterBtn = document.getElementById('chart-later');
    if (earlierBtn) earlierBtn.disabled = (w.start === 0);
    if (laterBtn) laterBtn.disabled = (page === 0);
  }}

  function render(i) {{
    selected = i;
    var week = WEEKS[i];
    var prev = i > 0 ? WEEKS[i - 1] : null;
    var isPartial = !!week.is_current;

    var pts = document.querySelectorAll('.pt.selected');
    for (var p = 0; p < pts.length; p++) pts[p].classList.remove('selected');
    var active = document.querySelectorAll('.pt[data-week="' + i + '"]');
    for (var a = 0; a < active.length; a++) active[a].classList.add('selected');

    METRICS.forEach(function (m) {{
      var valEl = document.getElementById(m.slug + '-value');
      var badgeEl = document.getElementById(m.slug + '-badge');
      if (valEl) valEl.textContent = fmtNum(week[m.field], m.decimals);
      if (badgeEl) {{
        var state = m.statusField ? acwrPill(week[m.statusField]) : badgeState(week[m.field], prev ? prev[m.field] : null, m.higherBetter, isPartial);
        badgeEl.className = 'delta' + (state.cls ? ' ' + state.cls : '');
        badgeEl.textContent = state.text;
      }}
    }});
    {race_js}

    var note = document.getElementById('week-note');
    if (note) {{
      var partialStr = isPartial ? ' (in progress)' : '';
      note.textContent = 'Week of ' + week.week_label + partialStr + ' – ' + week.n_activities + ' activities logged, ' + week.n_days_logged + ' days of wellness data';
    }}
    {activities_js}
    {extra_js}
  }}

  document.addEventListener('click', function (e) {{
    var pt = e.target.closest('.pt');
    if (!pt) return;
    var idx = parseInt(pt.getAttribute('data-week'), 10);
    if (!isNaN(idx)) render(idx);
  }});
  document.addEventListener('keydown', function (e) {{
    if (e.key !== 'Enter' && e.key !== ' ') return;
    var pt = e.target.closest && e.target.closest('.pt');
    if (!pt) return;
    e.preventDefault();
    var idx = parseInt(pt.getAttribute('data-week'), 10);
    if (!isNaN(idx)) render(idx);
  }});

  var earlierBtn = document.getElementById('chart-earlier');
  var laterBtn = document.getElementById('chart-later');
  if (earlierBtn) earlierBtn.addEventListener('click', function () {{
    if (page < totalPages - 1) {{ page++; renderCharts(); }}
  }});
  if (laterBtn) laterBtn.addEventListener('click', function () {{
    if (page > 0) {{ page--; renderCharts(); }}
  }});

  renderCharts();
  if (WEEKS.length) render(selected);
}})();
</script>"""


def render_training(data: dict, weeks: list) -> str:
    cards = "".join([
        card_skeleton("volume", "Weekly Volume", "mi"),
        card_skeleton("vert", "Total Vert", "ft"),
        card_skeleton("hr", "Avg Heart Rate", "bpm"),
        card_skeleton("vo2max", "VO2 Max", ""),
        card_skeleton("acwr", "Training Load (ACWR)", ""),
    ])

    metrics = [
        {"slug": "volume", "field": "volume_mi", "decimals": 1, "higherBetter": True, "kind": "bar"},
        {"slug": "vert", "field": "vert_ft", "decimals": 0, "higherBetter": True, "kind": "bar"},
        {"slug": "hr", "field": "avg_hr", "decimals": 0, "higherBetter": False, "kind": "line"},
        {"slug": "vo2max", "field": "vo2max", "decimals": 1, "higherBetter": True, "kind": "line"},
        {"slug": "acwr", "field": "acwr_ratio", "decimals": 2, "statusField": "acwr_status", "kind": "line"},
    ]

    body = f'''
  {chart_nav_html()}
  <div class="card-grid single-col side-training">{cards}</div>

  <div class="race-panel">
    <h2>Race Predictor</h2>
    <div class="race-grid">
      <div class="race-item"><div class="race-label">5K</div><div class="race-value" id="race-5k-value">–</div></div>
      <div class="race-item"><div class="race-label">10K</div><div class="race-value" id="race-10k-value">–</div></div>
      <div class="race-item"><div class="race-label">Half Marathon</div><div class="race-value" id="race-half-value">–</div></div>
      <div class="race-item"><div class="race-label">Marathon</div><div class="race-value" id="race-marathon-value">–</div></div>
    </div>
  </div>

  {build_personal_records(data)}

  {build_heatmap(data)}

  <div class="activities-panel">
    <h2>Activities This Week</h2>
    <div id="activities-list"></div>
  </div>

  {render_script(weeks, metrics, include_race_predictor=True, include_activities=True)}'''

    subtitle_id = '<span id="week-note"></span>'
    return page_shell("training.html", "Training", subtitle_id, body)


def render_recovery(data: dict, weeks: list) -> str:
    cards = "".join([
        card_skeleton("sleep", "Sleep", "h"),
        card_skeleton("rhr", "Resting HR", "bpm"),
        card_skeleton("hrv", "HRV", "ms"),
        card_skeleton("readiness", "Training Readiness", ""),
        card_skeleton("battery", "Body Battery (peak)", ""),
        card_skeleton("naps", "Naps", "min"),
        card_skeleton("spo2", "SpO2", "%"),
        card_skeleton("respiration", "Respiration", "brpm"),
    ])

    sleep_stage_card = '''
    <div class="card wide">
      <div class="card-head"><span class="card-title">Sleep Stages</span></div>
      <div class="stage-legend">
        <span><i class="swatch stage-deep"></i>Deep <b id="stage-deep-value">–</b></span>
        <span><i class="swatch stage-light"></i>Light <b id="stage-light-value">–</b></span>
        <span><i class="swatch stage-rem"></i>REM <b id="stage-rem-value">–</b></span>
        <span><i class="swatch stage-awake"></i>Awake <b id="stage-awake-value">–</b></span>
      </div>
      <div id="stage-chart"></div>
    </div>'''

    stress_dates = [row["date"] for row in weekly_stress_series(data)]
    stress_values = [row["value"] for row in weekly_stress_series(data)]
    stress_labels = [f"{MONTH_ABBR[datetime.strptime(d, '%Y-%m-%d').month - 1]} {datetime.strptime(d, '%Y-%m-%d').day} '{d[2:4]}" for d in stress_dates]
    stress_section = ""
    if stress_values:
        stress_section = f'''
  <div class="pr-panel">
    <h2>Weekly Stress (Garmin rollup)</h2>
    {static_line_chart(stress_values, stress_labels, 0)}
  </div>'''

    metrics = [
        {"slug": "sleep", "field": "sleep_h", "decimals": 1, "higherBetter": True, "kind": "line"},
        {"slug": "rhr", "field": "resting_hr", "decimals": 0, "higherBetter": False, "kind": "line"},
        {"slug": "hrv", "field": "hrv_ms", "decimals": 0, "higherBetter": True, "kind": "line"},
        {"slug": "readiness", "field": "readiness", "decimals": 0, "higherBetter": True, "kind": "line"},
        {"slug": "battery", "field": "body_battery_high", "decimals": 0, "higherBetter": True, "kind": "line"},
        {"slug": "naps", "field": "nap_minutes", "decimals": 0, "higherBetter": True, "kind": "bar"},
        {"slug": "spo2", "field": "avg_spo2", "decimals": 0, "higherBetter": True, "kind": "line"},
        {"slug": "respiration", "field": "avg_respiration", "decimals": 1, "higherBetter": False, "kind": "line"},
    ]

    stage_js = """
    [['deep', 'deep_sleep_h'], ['light', 'light_sleep_h'], ['rem', 'rem_sleep_h'], ['awake', 'awake_h']].forEach(function (pair) {
      var el = document.getElementById('stage-' + pair[0] + '-value');
      if (el) {
        var v = week[pair[1]];
        el.textContent = (v != null ? v.toFixed(1) + 'h' : '–');
      }
    });"""

    body = f'''
  {chart_nav_html()}
  <div class="card-grid single-col side-recovery">{cards}{sleep_stage_card}</div>
  {stress_section}
  {render_script(weeks, metrics, include_race_predictor=False, include_activities=False, extra_js=stage_js, include_stage_chart=True)}'''

    subtitle_id = '<span id="week-note"></span>'
    return page_shell("recovery.html", "Recovery", subtitle_id, body)


def render_daily(data: dict) -> str:
    days = compute_daily_days(data, days_back=90)
    days_json = json.dumps(days).replace("</", "<\\/")

    body = f'''
  <div class="chart-nav">
    <button id="day-prev" class="navbtn" type="button">&larr; Previous Day</button>
    <span id="day-label" class="chart-range"></span>
    <button id="day-next" class="navbtn" type="button">Next Day &rarr;</button>
  </div>

  <div class="pr-panel">
    <h2>Wellness</h2>
    <div class="pr-grid" id="daily-wellness-grid"></div>
  </div>

  <div class="race-panel">
    <h2>Race Predictor (as of this day)</h2>
    <div class="race-grid">
      <div class="race-item"><div class="race-label">5K</div><div class="race-value" id="day-race-5k">–</div></div>
      <div class="race-item"><div class="race-label">10K</div><div class="race-value" id="day-race-10k">–</div></div>
      <div class="race-item"><div class="race-label">Half Marathon</div><div class="race-value" id="day-race-half">–</div></div>
      <div class="race-item"><div class="race-label">Marathon</div><div class="race-value" id="day-race-marathon">–</div></div>
    </div>
  </div>

  <div class="activities-panel">
    <h2>Activities</h2>
    <div id="daily-activities-list"></div>
  </div>

<script id="days-data" type="application/json">{days_json}</script>
<script>
(function () {{
  var DAYS = JSON.parse(document.getElementById('days-data').textContent);
  var idx = DAYS.length - 1;

  var STATUS_LABELS = {{
    PEAKING: ['Peaking', 'good'], PRODUCTIVE: ['Productive', 'good'], MAINTAINING: ['Maintaining', 'good'],
    RECOVERY: ['Recovery', 'info'],
    OVERREACHING: ['Overreaching', 'warn'], UNPRODUCTIVE: ['Unproductive', 'warn'], DETRAINING: ['Detraining', 'warn'],
    NO_STATUS: ['No Status', 'info']
  }};

  function statusPill(raw) {{
    if (!raw) return ['–', 'info'];
    // Garmin appends a numeric device-index suffix (e.g. "PEAKING_1") to several
    // status codes, not just RECOVERY_1 -- strip any trailing "_<digits>" before matching.
    var key = raw.toUpperCase().replace(/_\\d+$/, '');
    if (STATUS_LABELS[key]) return STATUS_LABELS[key];
    return [raw.replace(/_/g, ' ').replace(/\\w\\S*/g, function (t) {{ return t.charAt(0).toUpperCase() + t.substr(1).toLowerCase(); }}), 'info'];
  }}

  function acwrPill(status) {{
    if (!status) return ['–', 'info'];
    var key = status.toUpperCase();
    var cls = key === 'HIGH' ? 'bad' : key === 'LOW' ? 'warn' : 'good';
    return [key.charAt(0) + key.slice(1).toLowerCase(), cls];
  }}

  function fmtRace(sec) {{
    if (sec === null || sec === undefined) return '–';
    sec = Math.round(sec);
    var h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    var mm = String(m).padStart(2, '0'), ss = String(s).padStart(2, '0');
    return h > 0 ? (h + ':' + mm + ':' + ss) : (m + ':' + ss);
  }}

  function fmtPace(secPerMi) {{
    if (secPerMi === null || secPerMi === undefined || !isFinite(secPerMi)) return '–';
    var m = Math.floor(secPerMi / 60), s = Math.round(secPerMi % 60);
    return m + ':' + String(s).padStart(2, '0') + '/mi';
  }}

  function fmtDuration(s) {{
    if (!s) return '–';
    var h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60);
    return h > 0 ? (h + 'h ' + m + 'm') : (m + 'm');
  }}

  function item(items, label, value, sub) {{
    if (value === null || value === undefined || value === '') return;
    items.push('<div class="pr-item"><div class="pr-label">' + label + '</div><div class="pr-value">' + value + '</div>' +
      (sub ? '<div class="pr-date">' + sub + '</div>' : '') + '</div>');
  }}

  function buildWellnessGrid(w) {{
    var items = [];
    item(items, 'Resting HR', w.resting_hr != null ? w.resting_hr + ' bpm' : null);
    item(items, 'HRV (overnight)', w.hrv_overnight != null ? Math.round(w.hrv_overnight) + ' ms' : null);
    item(items, 'Sleep', w.sleep_hours != null ? w.sleep_hours.toFixed(1) + ' h' : null,
      w.sleep_score != null ? 'score ' + w.sleep_score : null);
    if (w.deep_sleep_h != null || w.light_sleep_h != null || w.rem_sleep_h != null) {{
      var stages = 'Deep ' + (w.deep_sleep_h || 0).toFixed(1) + 'h, Light ' + (w.light_sleep_h || 0).toFixed(1) +
        'h, REM ' + (w.rem_sleep_h || 0).toFixed(1) + 'h, Awake ' + (w.awake_h || 0).toFixed(1) + 'h';
      item(items, 'Sleep Stages', stages);
    }}
    item(items, 'Nap', w.nap_minutes ? Math.round(w.nap_minutes) + ' min' : null);
    item(items, 'SpO2', w.avg_spo2 != null ? w.avg_spo2 + '%' : null);
    item(items, 'Respiration', w.avg_respiration != null ? w.avg_respiration.toFixed(1) + ' brpm' : null);
    item(items, 'Body Battery', (w.body_battery_low != null && w.body_battery_high != null) ?
      w.body_battery_low + ' \\u2192 ' + w.body_battery_high : null);
    item(items, 'Stress (avg)', w.avg_stress != null ? w.avg_stress : null);
    item(items, 'Steps', w.steps != null ? w.steps.toLocaleString() : null);
    item(items, 'Training Readiness', w.training_readiness != null ? w.training_readiness : null);
    item(items, 'VO2 Max', w.vo2max != null ? w.vo2max : null);
    if (w.training_status) {{
      var sp = statusPill(w.training_status);
      items.push('<div class="pr-item"><div class="pr-label">Training Status</div><div class="pr-value"><span class="pill pill-' +
        sp[1] + '">' + sp[0] + '</span></div></div>');
    }}
    if (w.acwr_ratio != null) {{
      var ap = acwrPill(w.acwr_status);
      items.push('<div class="pr-item"><div class="pr-label">ACWR</div><div class="pr-value">' + w.acwr_ratio.toFixed(2) +
        ' <span class="pill pill-' + ap[1] + '" style="font-size:12px">' + ap[0] + '</span></div></div>');
    }}
    item(items, 'Fitness Age', w.fitness_age != null ? w.fitness_age : null);
    if (w.heat_altitude_acclimation != null) item(items, 'Heat/Altitude Acclimation', String(w.heat_altitude_acclimation));
    return items.length ? items.join('') : '<p class="empty">No wellness data recorded for this day.</p>';
  }}

  function buildActivities(acts) {{
    if (!acts.length) return '<p class="empty">No activities recorded for this day.</p>';
    return acts.map(function (act) {{
      var timePart = act.start_local && act.start_local.indexOf(' ') > -1 ? act.start_local.split(' ')[1] : '';
      return '<div class="activity-row">' +
        '<div class="activity-main"><span class="activity-name">' + act.name + '</span>' +
        '<span class="activity-type">' + act.type + (timePart ? ' - ' + timePart : '') + '</span></div>' +
        '<div class="activity-stats">' +
        '<span>' + (act.distance_mi != null ? act.distance_mi.toFixed(2) + ' mi' : '–') + '</span>' +
        '<span>' + fmtDuration(act.duration_s) + '</span>' +
        '<span>' + fmtPace(act.pace_s_per_mi) + (act.gap_s_per_mi != null && Math.abs(act.gap_s_per_mi - act.pace_s_per_mi) > 1 ? ' <span class="activity-gap">(GAP ' + fmtPace(act.gap_s_per_mi) + ')</span>' : '') + '</span>' +
        '<span>' + (act.elevation_ft != null ? '+' + Math.round(act.elevation_ft) + ' ft' : '–') + '</span>' +
        '<span>' + (act.avg_elevation_ft != null ? Math.round(act.avg_elevation_ft) + ' ft alt' : '–') + '</span>' +
        '<span>' + (act.avg_hr != null ? Math.round(act.avg_hr) + ' bpm' : '–') + '</span>' +
        '<span>' + (act.calories != null ? Math.round(act.calories) + ' cal' : '–') + '</span>' +
        '</div></div>';
    }}).join('');
  }}

  function render(i) {{
    idx = i;
    var day = DAYS[i];
    document.getElementById('day-label').textContent = day.date_label;
    document.getElementById('daily-wellness-grid').innerHTML = buildWellnessGrid(day.wellness || {{}});
    document.getElementById('daily-activities-list').innerHTML = buildActivities(day.activities || []);

    var w = day.wellness || {{}};
    document.getElementById('day-race-5k').textContent = fmtRace(w.race_5k_s);
    document.getElementById('day-race-10k').textContent = fmtRace(w.race_10k_s);
    document.getElementById('day-race-half').textContent = fmtRace(w.race_half_s);
    document.getElementById('day-race-marathon').textContent = fmtRace(w.race_marathon_s);

    document.getElementById('day-prev').disabled = (i === 0);
    document.getElementById('day-next').disabled = (i === DAYS.length - 1);
  }}

  document.getElementById('day-prev').addEventListener('click', function () {{ if (idx > 0) render(idx - 1); }});
  document.getElementById('day-next').addEventListener('click', function () {{ if (idx < DAYS.length - 1) render(idx + 1); }});

  if (DAYS.length) render(idx);
}})();
</script>'''

    return page_shell("daily.html", "Daily", "Full detail for one day at a time, back 3 months", body)


def render_altitude(data: dict) -> str:
    stats = compute_altitude_stats(data)

    if not stats["activities_with_elevation"]:
        body = '''
  <div class="pr-panel">
    <h2>Altitude Adaptation</h2>
    <p class="empty">No activities with elevation data yet -- this fills in once GPS activities with altitude readings are synced.</p>
  </div>'''
        return page_shell("altitude.html", "Altitude", "Estimated from your elevation and pace/HR data", body)

    summary_items = f'''
      <div class="pr-item">
        <div class="pr-label">Highest Elevation Reached</div>
        <div class="pr-value">{fmt(stats["max_elevation_ft"], 0)} ft</div>
      </div>
      <div class="pr-item">
        <div class="pr-label">Avg Training Elevation (90d)</div>
        <div class="pr-value">{fmt(stats["avg_elevation_ft_90d"], 0)} ft</div>
      </div>
      <div class="pr-item">
        <div class="pr-label">High-Altitude Runs (90d, 9,000ft+)</div>
        <div class="pr-value">{stats["high_alt_count_90d"]}</div>
      </div>'''

    band_rows = "".join(
        f'''
      <div class="pr-item">
        <div class="pr-label">{b["label"]}</div>
        <div class="pr-value">{fmt_pace(b.get("avg_pace_s_per_mi")) if b.get("avg_pace_s_per_mi") else "–"}</div>
        <div class="pr-date">{b["count"]} runs{f", {b['avg_hr']:.0f} bpm avg" if b.get("avg_hr") else ""}{f", {b['efficiency']:.1f} bpm/mph" if b.get("efficiency") else ""}</div>
      </div>''' for b in stats["bands"]
    )

    eff_series = stats["efficiency_series"]
    chart_section = ""
    if len(eff_series) >= 2:
        eff_values = [round(e["efficiency"], 1) for e in eff_series]
        eff_labels = [
            f"{MONTH_ABBR[datetime.strptime(e['date'], '%Y-%m-%d').month - 1]} {datetime.strptime(e['date'], '%Y-%m-%d').day} '{e['date'][2:4]}"
            for e in eff_series
        ]
        chart_section = f'''
  <div class="pr-panel">
    <h2>Altitude Efficiency Trend</h2>
    <p class="empty">Heart-rate cost per mph of pace, for runs at 6,500 ft or higher, in chronological order. A downward trend suggests you're adapting to elevation -- less HR needed for the same effort.</p>
    {static_line_chart(eff_values, eff_labels, 1)}
  </div>'''

    body = f'''
  <div class="pr-panel">
    <h2>Altitude Snapshot</h2>
    <div class="pr-grid">{summary_items}</div>
  </div>

  <div class="pr-panel">
    <h2>Pace &amp; Heart Rate by Elevation Band</h2>
    <div class="pr-grid">{band_rows}</div>
  </div>
  {chart_section}
  <div class="pr-panel">
    <p class="empty">
      This is our own estimate, computed from your activities' real elevation, pace, and heart
      rate data -- Garmin doesn't provide a heat/altitude acclimation score for this account.
      There's no ambient temperature data available either, so this reflects altitude exposure
      only, not heat adaptation.
    </p>
  </div>'''

    return page_shell("altitude.html", "Altitude", "Estimated from your elevation and pace/HR data", body)


def render_lifetime(data: dict) -> str:
    stats = compute_lifetime_stats(data)

    type_rows = "".join(
        f'''
      <div class="pr-item">
        <div class="pr-label">{t["type"]}</div>
        <div class="pr-value">{fmt(t["distance_mi"], 0)} mi</div>
        <div class="pr-date">{t["count"]} activities</div>
      </div>''' for t in stats["by_type"]
    )

    coverage_note = ""
    if stats["lifetime_activity_count"] and stats["synced_activity_count"] < stats["lifetime_activity_count"]:
        coverage_note = (
            f'<p class="empty">Garmin reports {stats["lifetime_activity_count"]:,} lifetime activities total; '
            f'this dashboard has synced the most recent {stats["synced_activity_count"]:,} '
            f'(from {stats["earliest_synced"]} onward). Older history hasn\'t been pulled.</p>'
        )

    body = f'''
  <div class="pr-panel">
    <h2>All-Time Totals</h2>
    <div class="pr-grid">
      <div class="pr-item">
        <div class="pr-label">Lifetime Activities (Garmin)</div>
        <div class="pr-value">{fmt(stats["lifetime_activity_count"], 0) if stats["lifetime_activity_count"] else "–"}</div>
      </div>
      <div class="pr-item">
        <div class="pr-label">Synced Activities</div>
        <div class="pr-value">{stats["synced_activity_count"]:,}</div>
      </div>
      <div class="pr-item">
        <div class="pr-label">Total Distance</div>
        <div class="pr-value">{fmt(stats["total_distance_mi"], 0)} mi</div>
      </div>
      <div class="pr-item">
        <div class="pr-label">Total Vert</div>
        <div class="pr-value">{fmt(stats["total_vert_ft"], 0)} ft</div>
      </div>
      <div class="pr-item">
        <div class="pr-label">Total Time</div>
        <div class="pr-value">{fmt(stats["total_duration_s"] / 3600, 0)} h</div>
      </div>
    </div>
    {coverage_note}
  </div>

  <div class="pr-panel">
    <h2>By Activity Type (synced history)</h2>
    <div class="pr-grid">{type_rows}</div>
  </div>'''

    return page_shell("lifetime.html", "Lifetime", "All-time totals across your Garmin history", body)


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
    --warn: #a9720f;
    --info: #45688f;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #141a19; --surface: #1c2422; --surface-2: #202a28;
      --ink: #edefee; --ink-muted: #9bb0ab; --border: #2b3432;
      --training: #cc7038; --training-soft: rgba(204, 112, 56, 0.16);
      --recovery: #1f9e96; --recovery-soft: rgba(31, 158, 150, 0.16);
      --good: #4fbf82; --bad: #e2685a;
      --warn: #e0a83e; --info: #7ea3d1;
    }
  }
  :root[data-theme="dark"] {
    --bg: #141a19; --surface: #1c2422; --surface-2: #202a28;
    --ink: #edefee; --ink-muted: #9bb0ab; --border: #2b3432;
    --training: #cc7038; --training-soft: rgba(204, 112, 56, 0.16);
    --recovery: #1f9e96; --recovery-soft: rgba(31, 158, 150, 0.16);
    --good: #4fbf82; --bad: #e2685a;
    --warn: #e0a83e; --info: #7ea3d1;
  }
  :root[data-theme="light"] {
    --bg: #eef2f1; --surface: #ffffff; --surface-2: #f5f8f7;
    --ink: #1a1f1e; --ink-muted: #5c6664; --border: #dde3e1;
    --training: #c1652b; --training-soft: rgba(193, 101, 43, 0.14);
    --recovery: #03948a; --recovery-soft: rgba(3, 148, 138, 0.14);
    --good: #1f7a4c; --bad: #b23b2e;
    --warn: #a9720f; --info: #45688f;
  }

  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; min-height: 100%; }
  html { background: var(--bg); }
  body { background: var(--bg); }

  .dashboard {
    background: var(--bg);
    color: var(--ink);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    padding: 28px clamp(16px, 4vw, 40px) 40px;
    max-width: 1180px;
    margin: 0 auto;
  }

  .topbar {
    display: flex; justify-content: space-between; align-items: flex-end;
    flex-wrap: wrap; gap: 12px;
    border-bottom: 1px solid var(--border);
    padding-bottom: 18px; margin-bottom: 28px;
  }
  .topbar h1 {
    font-family: Georgia, "Iowan Old Style", "Times New Roman", serif;
    font-size: clamp(24px, 3.4vw, 32px);
    font-weight: 600; margin: 0 0 4px; letter-spacing: -0.01em;
  }
  .subtitle { margin: 0; color: var(--ink-muted); font-size: 14px; }
  .topbar-meta { text-align: right; font-size: 12px; color: var(--ink-muted); line-height: 1.5; }
  .topbar-meta strong {
    color: var(--ink);
    font-family: ui-monospace, "Cascadia Code", "SF Mono", Consolas, monospace;
    font-size: 13px; font-weight: 500;
  }

  .columns { display: grid; grid-template-columns: 1fr 1fr; gap: 28px; }
  @media (max-width: 720px) { .columns { grid-template-columns: 1fr; } }

  .side h2 {
    display: flex; align-items: center; gap: 8px;
    font-size: 13px; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.08em; color: var(--ink-muted); margin: 0 0 14px;
  }
  .side-dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
  .dot-training { background: var(--training); }
  .dot-recovery { background: var(--recovery); }

  .card-grid { display: flex; flex-direction: column; gap: 14px; }

  .card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 10px; padding: 16px 18px 12px;
  }
  .side-training .card { border-left: 3px solid var(--training); }
  .side-recovery .card { border-left: 3px solid var(--recovery); }

  .card-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
  .card-title {
    font-size: 12.5px; font-weight: 600; color: var(--ink-muted);
    text-transform: uppercase; letter-spacing: 0.04em;
  }
  .delta {
    font-size: 11.5px; font-weight: 600; padding: 2px 7px; border-radius: 20px;
    background: var(--surface-2); color: var(--ink-muted);
  }
  .delta.good { color: var(--good); background: color-mix(in srgb, var(--good) 14%, transparent); }
  .delta.bad { color: var(--bad); background: color-mix(in srgb, var(--bad) 14%, transparent); }
  .delta.flat { color: var(--ink-muted); }

  .card-value {
    font-family: ui-monospace, "Cascadia Code", "SF Mono", Consolas, monospace;
    font-size: 28px; font-weight: 600; font-variant-numeric: tabular-nums; margin-bottom: 6px;
  }
  .card-unit {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 13px; font-weight: 500; color: var(--ink-muted); margin-left: 4px;
  }

  .spark { width: 100%; height: auto; display: block; overflow: visible; }
  .spark-grid { stroke: var(--border); stroke-width: 1; }
  .spark-tick { font-size: 9px; fill: var(--ink-muted); }
  .spark-empty { font-size: 11px; fill: var(--ink-muted); }
  .pt { cursor: pointer; }
  .pt:focus { outline: none; }

  /* Default colors for standalone charts (e.g. Weekly Stress, Altitude Efficiency)
     not scoped under .side-training/.side-recovery. */
  .spark-line { stroke: var(--info); stroke-width: 2; fill: none; }
  .spark-area { fill: color-mix(in srgb, var(--info) 16%, transparent); stroke: none; }
  .dot { fill: var(--info); opacity: 0.55; }
  .dot-current { fill: var(--info); }

  .side-training .spark-line { stroke: var(--training); stroke-width: 2; fill: none; }
  .side-training .spark-area { fill: var(--training-soft); stroke: none; }
  .side-training .dot { fill: var(--training); opacity: 0.55; }
  .side-training .dot-current { fill: var(--training); }
  .side-training .dot.selected { opacity: 1; r: 4.5; }
  .side-training .bar { fill: var(--training); opacity: 0.45; }
  .side-training .bar-current { fill: var(--training); }
  .side-training .bar.selected { opacity: 0.9; }

  .side-recovery .spark-line { stroke: var(--recovery); stroke-width: 2; fill: none; }
  .side-recovery .spark-area { fill: var(--recovery-soft); stroke: none; }
  .side-recovery .dot { fill: var(--recovery); opacity: 0.55; }
  .side-recovery .dot-current { fill: var(--recovery); }
  .side-recovery .dot.selected { opacity: 1; }
  .side-recovery .bar { fill: var(--recovery); opacity: 0.45; }
  .side-recovery .bar-current { fill: var(--recovery); }
  .side-recovery .bar.selected { opacity: 0.9; }

  .selected { stroke: var(--ink); stroke-width: 1.5; }

  .race-panel {
    margin-top: 28px; background: var(--surface); border: 1px solid var(--border);
    border-radius: 10px; padding: 18px 20px;
  }
  .race-panel h2 {
    font-size: 13px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--ink-muted); margin: 0 0 14px;
  }
  .race-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }
  @media (max-width: 560px) { .race-grid { grid-template-columns: 1fr 1fr; } }
  .race-item { text-align: center; }
  .race-label { font-size: 11.5px; color: var(--ink-muted); text-transform: uppercase; letter-spacing: 0.05em; }
  .race-value {
    font-family: ui-monospace, "Cascadia Code", "SF Mono", Consolas, monospace;
    font-size: 22px; font-weight: 600; margin-top: 4px; font-variant-numeric: tabular-nums;
  }

  .activities-panel {
    margin-top: 20px; background: var(--surface); border: 1px solid var(--border);
    border-radius: 10px; padding: 18px 20px;
  }
  .activities-panel h2 {
    font-size: 13px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--ink-muted); margin: 0 0 14px;
  }
  .activity-row {
    display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap;
    gap: 8px; padding: 10px 0; border-top: 1px solid var(--border);
  }
  .activity-row:first-child { border-top: none; }
  .activity-main { display: flex; flex-direction: column; min-width: 140px; }
  .activity-name { font-weight: 600; font-size: 14px; }
  .activity-type { font-size: 11.5px; color: var(--ink-muted); text-transform: capitalize; }
  .activity-stats {
    display: flex; gap: 16px; font-size: 13px; color: var(--ink-muted);
    font-family: ui-monospace, "Cascadia Code", "SF Mono", Consolas, monospace;
    font-variant-numeric: tabular-nums; flex-wrap: wrap;
  }
  .activities-panel .empty { color: var(--ink-muted); font-size: 13px; margin: 0; }
  .activity-gap { color: var(--ink-muted); font-size: 11px; }

  .race-countdown {
    margin-bottom: 24px; background: var(--surface); border: 1px solid var(--border);
    border-radius: 10px; padding: 18px 22px; display: flex; justify-content: space-between;
    align-items: center; flex-wrap: wrap; gap: 16px;
  }
  .countdown-days {
    font-family: Georgia, "Iowan Old Style", "Times New Roman", serif;
    font-size: 30px; font-weight: 600;
  }
  .countdown-sub { color: var(--ink-muted); font-size: 13px; margin-top: 2px; }
  .countdown-stats { display: flex; gap: 28px; flex-wrap: wrap; }
  .countdown-stat { text-align: center; }
  .countdown-stat .stat-label {
    font-size: 11px; color: var(--ink-muted); text-transform: uppercase; letter-spacing: 0.05em;
  }
  .countdown-stat .stat-value {
    font-family: ui-monospace, "Cascadia Code", "SF Mono", Consolas, monospace;
    font-size: 18px; font-weight: 600; margin-top: 2px; font-variant-numeric: tabular-nums;
    display: flex; align-items: center; gap: 6px; justify-content: center;
  }

  .pr-panel, .fitness-panel, .heatmap-panel {
    margin-top: 20px; background: var(--surface); border: 1px solid var(--border);
    border-radius: 10px; padding: 18px 20px;
  }
  .pr-panel h2, .fitness-panel h2, .heatmap-panel h2 {
    font-size: 13px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--ink-muted); margin: 0 0 14px;
  }
  .pr-grid, .fact-grid {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 16px;
  }
  .pr-item, .fact-item { text-align: left; }
  .pr-label, .fact-label {
    font-size: 11px; color: var(--ink-muted); text-transform: uppercase; letter-spacing: 0.05em;
  }
  .pr-value, .fact-value {
    font-family: ui-monospace, "Cascadia Code", "SF Mono", Consolas, monospace;
    font-size: 19px; font-weight: 600; margin-top: 3px; font-variant-numeric: tabular-nums;
  }
  .pr-date { font-size: 11px; color: var(--ink-muted); margin-top: 2px; }
  .fact-sub { font-size: 12px; color: var(--ink-muted); font-weight: 500; }

  .pill {
    display: inline-block; padding: 3px 10px; border-radius: 20px; font-size: 14px; font-weight: 600;
  }
  .pill-good { color: var(--good); background: color-mix(in srgb, var(--good) 16%, transparent); }
  .pill-bad { color: var(--bad); background: color-mix(in srgb, var(--bad) 16%, transparent); }
  .pill-warn { color: var(--warn); background: color-mix(in srgb, var(--warn) 16%, transparent); }
  .pill-info { color: var(--info); background: color-mix(in srgb, var(--info) 16%, transparent); }

  .heatmap-grid { display: flex; gap: 3px; overflow-x: auto; padding-bottom: 4px; }
  .heat-col { display: flex; flex-direction: column; gap: 3px; }
  .heat-cell { width: 11px; height: 11px; border-radius: 2px; background: var(--surface-2); }
  .heat-1 { background: var(--training-soft); }
  .heat-2 { background: color-mix(in srgb, var(--training) 45%, var(--surface-2)); }
  .heat-3 { background: color-mix(in srgb, var(--training) 70%, var(--surface-2)); }
  .heat-4 { background: var(--training); }

  .foot { margin-top: 32px; text-align: center; font-size: 12px; color: var(--ink-muted); }

  .pagenav {
    display: flex; gap: 4px; margin-bottom: 24px; border-bottom: 1px solid var(--border);
    flex-wrap: wrap;
  }
  .navlink {
    padding: 8px 14px; font-size: 13px; font-weight: 600; color: var(--ink-muted);
    text-decoration: none; border-bottom: 2px solid transparent; margin-bottom: -1px;
  }
  .navlink:hover { color: var(--ink); }
  .navlink.active { color: var(--training); border-bottom-color: var(--training); }

  .menu-grid {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px;
    margin: 24px 0;
  }
  .menu-card {
    display: block; background: var(--surface); border: 1px solid var(--border);
    border-radius: 10px; padding: 18px 20px; text-decoration: none; color: var(--ink);
    transition: border-color 0.15s ease;
  }
  .menu-card:hover { border-color: var(--training); }
  .menu-title {
    font-family: Georgia, "Iowan Old Style", "Times New Roman", serif;
    font-size: 19px; font-weight: 600; margin-bottom: 6px;
  }
  .menu-desc { font-size: 13px; color: var(--ink-muted); line-height: 1.4; }

  .card-grid.single-col {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 14px;
  }
  .card.wide { grid-column: 1 / -1; }

  .stage-legend {
    display: flex; gap: 16px; flex-wrap: wrap; font-size: 12.5px; color: var(--ink-muted);
    margin-bottom: 8px;
  }
  .stage-legend b { color: var(--ink); font-variant-numeric: tabular-nums; }
  .swatch {
    display: inline-block; width: 9px; height: 9px; border-radius: 2px; margin-right: 5px;
  }
  .swatch.stage-deep { background: var(--recovery); }
  .swatch.stage-light { background: color-mix(in srgb, var(--recovery) 55%, var(--surface-2)); }
  .swatch.stage-rem { background: var(--training); }
  .swatch.stage-awake { background: var(--border); }
  rect.stage-deep { fill: var(--recovery); }
  rect.stage-light { fill: color-mix(in srgb, var(--recovery) 55%, var(--surface-2)); }
  rect.stage-rem { fill: var(--training); }
  rect.stage-awake { fill: var(--border); }

  .chart-nav {
    display: flex; align-items: center; justify-content: center; gap: 16px;
    margin-bottom: 18px;
  }
  .navbtn {
    background: var(--surface); border: 1px solid var(--border); color: var(--ink);
    font-size: 13px; font-weight: 600; padding: 6px 14px; border-radius: 20px;
    cursor: pointer; font-family: inherit;
  }
  .navbtn:hover:not(:disabled) { border-color: var(--training); }
  .navbtn:disabled { opacity: 0.35; cursor: default; }
  .chart-range {
    font-family: ui-monospace, "Cascadia Code", "SF Mono", Consolas, monospace;
    font-size: 12.5px; color: var(--ink-muted); min-width: 160px; text-align: center;
  }
</style>
"""




def main():
    data = load_data()
    weeks = bucket_weeks(data)
    out_dir = OUT_PATH.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    pages = {
        "index.html": render_index(data, weeks),
        "training.html": render_training(data, weeks),
        "recovery.html": render_recovery(data, weeks),
        "daily.html": render_daily(data),
        "altitude.html": render_altitude(data),
        "lifetime.html": render_lifetime(data),
    }
    for filename, html in pages.items():
        (out_dir / filename).write_text(html, encoding="utf-8")

    print(f"Aggregated {len(weeks)} weeks. Wrote {len(pages)} pages to {out_dir}")


if __name__ == "__main__":
    main()
