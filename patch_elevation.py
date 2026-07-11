#!/usr/bin/env python3
"""One-off: backfill new activity fields (elevation, moving duration) into
existing activities without a full resync.

Re-fetches activities for the full historical range (one bulk API call) and
merges the fields into garmin/data.json, leaving wellness untouched.
"""

import json
from datetime import date, timedelta
from pathlib import Path

from sync_garmin import DEFAULT_TOKENSTORE, activity_fields, login_or_resume

HERE = Path(__file__).resolve().parent
DATA_PATH = HERE / "garmin" / "data.json"

DAYS = 555


def main():
    garmin = login_or_resume(DEFAULT_TOKENSTORE)
    today = date.today()
    start = (today - timedelta(days=DAYS - 1)).isoformat()
    raw = garmin.get_activities_by_date(start, today.isoformat())

    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    updated = 0
    for act in raw:
        f = activity_fields(act)
        existing = data["activities"].get(f["file"])
        if existing is not None:
            existing["min_elevation_m"] = f["min_elevation_m"]
            existing["max_elevation_m"] = f["max_elevation_m"]
            existing["avg_elevation_m"] = f["avg_elevation_m"]
            existing["moving_duration_s"] = f["moving_duration_s"]
            existing["activity_id"] = f["activity_id"]
            updated += 1

    DATA_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Patched elevation + moving-duration fields into {updated} activities.")


if __name__ == "__main__":
    main()
