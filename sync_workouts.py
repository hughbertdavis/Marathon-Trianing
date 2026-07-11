#!/usr/bin/env python3
"""Fetch per-lap splits for running activities and cache them in garmin/workouts.json.

One API call per activity, so this only processes running activities within
--days (default 180, i.e. ~6 months) and skips activities already cached --
safe to re-run daily to pick up new runs.
"""

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

from sync_garmin import DEFAULT_TOKENSTORE, login_or_resume, safe

HERE = Path(__file__).resolve().parent
DATA_PATH = HERE / "garmin" / "data.json"
WORKOUTS_PATH = HERE / "garmin" / "workouts.json"


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=180, help="How many days back to process (default 180 / ~6mo)")
    args = parser.parse_args()

    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    workouts = {}
    if WORKOUTS_PATH.exists():
        workouts = json.loads(WORKOUTS_PATH.read_text(encoding="utf-8"))

    cutoff = (date.today() - timedelta(days=args.days - 1)).isoformat()

    candidates = [
        a for a in data.get("activities", {}).values()
        if "running" in (a.get("type") or "").lower()
        and a.get("date") and a["date"] >= cutoff
        and a.get("activity_id")
        and a["file"] not in workouts
    ]

    if not candidates:
        print("No new running activities need splits.")
        return

    garmin = login_or_resume(DEFAULT_TOKENSTORE)
    fetched = 0
    for a in candidates:
        splits = safe(lambda: garmin.get_activity_splits(a["activity_id"]))
        laps = (splits or {}).get("lapDTOs") or []
        workouts[a["file"]] = {
            "activity_id": a["activity_id"],
            "date": a["date"],
            "laps": [lap_fields(l) for l in laps],
        }
        fetched += 1

    WORKOUTS_PATH.write_text(json.dumps(workouts, indent=2), encoding="utf-8")
    print(f"Fetched splits for {fetched} activities ({len(workouts)} total cached).")


if __name__ == "__main__":
    main()
