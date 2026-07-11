#!/usr/bin/env python3
"""Fetch per-lap splits and time-series detail for running activities, cached
in garmin/workouts.json.

Two API calls per activity (splits + details), so this only processes running
activities within --days (default 180, i.e. ~6 months) and skips activities
that are already fully cached -- safe to re-run daily to pick up new runs.

The time series (timestamp/distance/heart-rate/elevation, downsampled) is what
lets the dashboard's classifier spot real interval structure -- Garmin's watch
auto-pauses recording during a full-stop recovery, and that gap (plus the
heart-rate drop across it) is a much more reliable rep boundary than the
official lap splits, which often split one hard rep in two (an auto-lap firing
mid-interval) or merge reps together.
"""

import argparse
import json
import time
from datetime import date, timedelta
from pathlib import Path

from sync_garmin import DEFAULT_TOKENSTORE, login_or_resume, safe

HERE = Path(__file__).resolve().parent
DATA_PATH = HERE / "garmin" / "data.json"
WORKOUTS_PATH = HERE / "garmin" / "workouts.json"

SERIES_DOWNSAMPLE = 4  # keep every Nth raw sample (~2s cadence -> ~8s)


def lap_fields(lap: dict) -> dict:
    return {
        "distance_m": lap.get("distance"),
        "duration_s": lap.get("duration"),
        "moving_duration_s": lap.get("movingDuration"),
        "avg_hr": lap.get("averageHR"),
        "max_hr": lap.get("maxHR"),
        "elevation_gain_m": lap.get("elevationGain"),
        "elevation_loss_m": lap.get("elevationLoss"),
        "start_time_gmt": lap.get("startTimeGMT"),
    }


def fetch_series(garmin, activity_id):
    """Downsampled (timestamp, distance, heart-rate, elevation) time series."""
    details = safe(lambda: garmin.get_activity_details(activity_id))
    if not details:
        return None
    descs = {md["key"]: md["metricsIndex"] for md in details.get("metricDescriptors") or []}
    needed = ["directTimestamp", "sumDistance", "directHeartRate"]
    if not all(k in descs for k in needed):
        return None
    i_ts = descs["directTimestamp"]
    i_d = descs["sumDistance"]
    i_hr = descs["directHeartRate"]
    i_ele = descs.get("directElevation")

    metrics = details.get("activityDetailMetrics") or []
    if len(metrics) < 4:
        return None

    t0 = metrics[0]["metrics"][i_ts]
    t, d, hr, ele = [], [], [], []
    for m in metrics[::SERIES_DOWNSAMPLE]:
        row = m["metrics"]
        t.append(round((row[i_ts] - t0) / 1000.0))
        d.append(round(row[i_d] or 0))
        hr.append(round(row[i_hr]) if row[i_hr] else None)
        if i_ele is not None and row[i_ele] is not None:
            ele.append(round(row[i_ele], 1))
        else:
            ele.append(None)

    return {"t": t, "d": d, "hr": hr, "ele": ele}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=180, help="How many days back to process (default 180 / ~6mo)")
    args = parser.parse_args()

    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    workouts = {}
    if WORKOUTS_PATH.exists():
        workouts = json.loads(WORKOUTS_PATH.read_text(encoding="utf-8"))

    cutoff = (date.today() - timedelta(days=args.days - 1)).isoformat()

    all_running = [
        a for a in data.get("activities", {}).values()
        if "running" in (a.get("type") or "").lower()
        and a.get("date") and a["date"] >= cutoff
        and a.get("activity_id")
    ]

    needs_laps = [a for a in all_running if a["file"] not in workouts]
    needs_series = [a for a in all_running if "series" not in workouts.get(a["file"], {})]

    if not needs_laps and not needs_series:
        print("No new running activities need splits or series data.")
        return

    garmin = login_or_resume(DEFAULT_TOKENSTORE)

    for a in needs_laps:
        splits = safe(lambda: garmin.get_activity_splits(a["activity_id"]))
        laps = (splits or {}).get("lapDTOs") or []
        workouts[a["file"]] = {
            "activity_id": a["activity_id"],
            "date": a["date"],
            "laps": [lap_fields(l) for l in laps],
        }
        time.sleep(0.2)

    for a in needs_series:
        series = fetch_series(garmin, a["activity_id"])
        if series:
            workouts[a["file"]]["series"] = series
        time.sleep(0.2)

    WORKOUTS_PATH.write_text(json.dumps(workouts, indent=2), encoding="utf-8")
    print(f"Fetched laps for {len(needs_laps)} and series for {len(needs_series)} activities ({len(workouts)} total cached).")


if __name__ == "__main__":
    main()
