#!/usr/bin/env python3
"""Pull Garmin Connect activity + wellness data into local markdown/JSON notes.

Built on python-garminconnect (https://github.com/cyberjunky/python-garminconnect).
Read-only: never writes anything back to your Garmin account.
"""

import argparse
import getpass
import json
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path

from garminconnect import Garmin

HERE = Path(__file__).resolve().parent
DEFAULT_TOKENSTORE = str(HERE / ".garmin_tokens")
DEFAULT_OUT = str(HERE / "garmin")


def _prompt_mfa() -> str:
    return input("Enter the 2FA/MFA code Garmin just sent you: ").strip()


def safe(fn):
    try:
        return fn()
    except Exception:
        return None


def resolve_tokenstore(cli_value: str) -> str:
    # In CI, GARMINTOKENS holds the token data itself (not a path) -- take priority.
    return os.getenv("GARMINTOKENS") or cli_value


def do_login(tokenstore: str) -> None:
    email = input("Garmin email: ").strip()
    password = getpass.getpass("Garmin password (hidden, nothing will show as you type): ")
    garmin = Garmin(email=email, password=password, prompt_mfa=_prompt_mfa)
    garmin.login(tokenstore)
    print(f"\nLogged in. Session saved to: {tokenstore}")
    print("This session lasts about a year -- you won't need to log in again until it expires.")


def do_print_token(tokenstore: str) -> None:
    garmin = Garmin()
    garmin.login(tokenstore)
    print(garmin.client.dumps())


def login_or_resume(tokenstore_arg: str) -> Garmin:
    tokenstore = resolve_tokenstore(tokenstore_arg)
    garmin = Garmin()
    try:
        garmin.login(tokenstore)
        return garmin
    except Exception as e:
        sys.exit(
            "No saved Garmin session found (or it's expired/invalid): "
            f"{e}\nRun: python sync_garmin.py --login"
        )


def fmt_hms(seconds) -> str | None:
    if not seconds:
        return None
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, _ = divmod(rem, 60)
    return f"{h}h {m}m" if h else f"{m}m"


def wellness_fields(garmin: Garmin, day: date) -> dict:
    cdate = day.isoformat()
    stats = safe(lambda: garmin.get_stats(cdate)) or {}
    sleep = safe(lambda: garmin.get_sleep_data(cdate)) or {}
    hrv = safe(lambda: garmin.get_hrv_data(cdate)) or {}
    readiness = safe(lambda: garmin.get_training_readiness(cdate)) or []

    daily_sleep = (sleep or {}).get("dailySleepDTO") or {}
    sleep_scores = daily_sleep.get("sleepScores") or {}
    overall_score = (sleep_scores.get("overall") or {}).get("value")
    sleep_seconds = daily_sleep.get("sleepTimeSeconds")

    hrv_summary = (hrv or {}).get("hrvSummary") or {}
    last_night_hrv = hrv_summary.get("lastNightAvg")

    readiness_score = None
    if isinstance(readiness, list) and readiness:
        readiness_score = readiness[0].get("score")

    avg_stress = stats.get("averageStressLevel")

    return {
        "date": cdate,
        "resting_hr": stats.get("restingHeartRate"),
        "hrv_overnight": last_night_hrv,
        "sleep_hours": (sleep_seconds / 3600) if sleep_seconds else None,
        "sleep_score": overall_score,
        "body_battery_low": stats.get("bodyBatteryLowestValue"),
        "body_battery_high": stats.get("bodyBatteryHighestValue"),
        "avg_stress": avg_stress if (avg_stress is not None and avg_stress >= 0) else None,
        "steps": stats.get("totalSteps"),
        "training_readiness": readiness_score,
    }


def render_wellness_note(f: dict) -> str:
    lines = [f"# Garmin wellness {f['date']}", ""]

    if f["resting_hr"] is not None:
        lines.append(f"- Resting HR: {f['resting_hr']} bpm")
    if f["hrv_overnight"] is not None:
        lines.append(f"- HRV (overnight): {f['hrv_overnight']:.0f} ms")
    if f["sleep_hours"]:
        score_str = f" (score {f['sleep_score']})" if f["sleep_score"] is not None else ""
        lines.append(f"- Sleep: {f['sleep_hours']:.1f} h{score_str}")
    if f["body_battery_low"] is not None and f["body_battery_high"] is not None:
        lines.append(f"- Body battery: {f['body_battery_low']} -> {f['body_battery_high']}")
    if f["avg_stress"] is not None:
        lines.append(f"- Stress (avg): {f['avg_stress']}")
    if f["steps"] is not None:
        lines.append(f"- Steps: {f['steps']}")
    if f["training_readiness"] is not None:
        lines.append(f"- Training readiness: {f['training_readiness']}")

    if len(lines) == 2:
        lines.append("- (No wellness data synced for this day)")

    return "\n".join(lines) + "\n"


def activity_fields(act: dict) -> dict:
    name = act.get("activityName") or "Activity"
    start_local = act.get("startTimeLocal") or ""
    type_key = ((act.get("activityType") or {}).get("typeKey")) or "activity"
    date_part = start_local.split(" ")[0] if start_local else "unknown-date"
    time_part = start_local.split(" ")[1].replace(":", "") if " " in start_local else ""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "activity"
    filename = f"{date_part}-{time_part}-{slug}.md" if time_part else f"{date_part}-{slug}.md"

    return {
        "file": filename,
        "name": name,
        "date": date_part,
        "start_local": start_local,
        "type": type_key,
        "duration_s": act.get("duration"),
        "distance_m": act.get("distance"),
        "elevation_gain_m": act.get("elevationGain"),
        "avg_hr": act.get("averageHR"),
        "calories": act.get("calories"),
    }


def render_activity_note(f: dict) -> str:
    lines = [f"# {f['name']}", "", f"- Date: {f['start_local']}", f"- Type: {f['type']}"]
    if f["distance_m"]:
        lines.append(f"- Distance: {f['distance_m'] / 1000:.2f} km")
    if f["duration_s"]:
        lines.append(f"- Duration: {fmt_hms(f['duration_s'])}")
    if f["elevation_gain_m"]:
        lines.append(f"- Elevation gain: {f['elevation_gain_m']:.0f} m")
    if f["avg_hr"]:
        lines.append(f"- Avg HR: {f['avg_hr']:.0f} bpm")
    if f["calories"]:
        lines.append(f"- Calories: {f['calories']:.0f}")

    return "\n".join(lines) + "\n"


def sync(garmin: Garmin, days: int, out_dir: str, dry_run: bool) -> None:
    out = Path(out_dir)
    today = date.today()

    wellness = []
    for i in range(days):
        day = today - timedelta(days=i)
        fields = wellness_fields(garmin, day)
        wellness.append(fields)
        if dry_run:
            print(render_wellness_note(fields))

    start = (today - timedelta(days=days - 1)).isoformat()
    raw_activities = safe(lambda: garmin.get_activities_by_date(start, today.isoformat())) or []
    activities = [activity_fields(act) for act in raw_activities]
    if dry_run:
        for a in activities:
            print(f"--- {a['file']} ---")
            print(render_activity_note(a))

    if dry_run:
        return

    daily_dir = out / "daily"
    act_dir = out / "activities"
    daily_dir.mkdir(parents=True, exist_ok=True)
    act_dir.mkdir(parents=True, exist_ok=True)

    for f in wellness:
        (daily_dir / f"{f['date']}.md").write_text(render_wellness_note(f), encoding="utf-8")
    for a in activities:
        (act_dir / a["file"]).write_text(render_activity_note(a), encoding="utf-8")

    json_path = out / "data.json"
    existing = {"wellness": {}, "activities": {}}
    if json_path.exists():
        existing = json.loads(json_path.read_text(encoding="utf-8"))
        existing.setdefault("wellness", {})
        existing.setdefault("activities", {})

    for f in wellness:
        existing["wellness"][f["date"]] = f
    for a in activities:
        existing["activities"][a["file"]] = a

    json_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    print(f"Wrote {len(wellness)} daily notes and {len(activities)} activity notes to {out}/")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--login", action="store_true", help="Interactive one-time login")
    parser.add_argument(
        "--print-token", action="store_true",
        help="Print the saved session (for setting a CI secret); never share the output",
    )
    parser.add_argument("--days", type=int, default=3, help="How many days back to sync")
    parser.add_argument("--out", default=DEFAULT_OUT, help="Output folder")
    parser.add_argument("--tokenstore", default=DEFAULT_TOKENSTORE, help="Local session storage path")
    parser.add_argument("--dry-run", action="store_true", help="Print results, don't write files")
    args = parser.parse_args()

    if args.login:
        do_login(args.tokenstore)
        return

    if args.print_token:
        do_print_token(args.tokenstore)
        return

    garmin = login_or_resume(args.tokenstore)
    sync(garmin, args.days, args.out, args.dry_run)


if __name__ == "__main__":
    main()
