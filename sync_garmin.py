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
from datetime import date, datetime, timedelta
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


def wellness_fields(garmin: Garmin, day: date, race_by_date: dict | None = None) -> dict:
    cdate = day.isoformat()
    stats = safe(lambda: garmin.get_stats(cdate)) or {}
    sleep = safe(lambda: garmin.get_sleep_data(cdate)) or {}
    hrv = safe(lambda: garmin.get_hrv_data(cdate)) or {}
    readiness = safe(lambda: garmin.get_training_readiness(cdate)) or []
    max_metrics = safe(lambda: garmin.get_max_metrics(cdate)) or []
    training_status = safe(lambda: garmin.get_training_status(cdate)) or {}
    fitness_age = safe(lambda: garmin.get_fitnessage_data(cdate)) or {}

    daily_sleep = (sleep or {}).get("dailySleepDTO") or {}
    sleep_scores = daily_sleep.get("sleepScores") or {}
    overall_score = (sleep_scores.get("overall") or {}).get("value")
    sleep_seconds = daily_sleep.get("sleepTimeSeconds")

    hrv_summary = (hrv or {}).get("hrvSummary") or {}
    last_night_hrv = hrv_summary.get("lastNightAvg")

    readiness_score = None
    if isinstance(readiness, list) and readiness:
        readiness_score = readiness[0].get("score")

    vo2max = None
    heat_altitude = None
    if isinstance(max_metrics, list) and max_metrics:
        vo2max = (max_metrics[0].get("generic") or {}).get("vo2MaxValue")
        heat_altitude = max_metrics[0].get("heatAltitudeAcclimation")

    avg_stress = stats.get("averageStressLevel")

    race = (race_by_date or {}).get(cdate) or {}

    status_phrase = None
    acwr_ratio = None
    acwr_status = None
    latest_status = (training_status.get("mostRecentTrainingStatus") or {}).get("latestTrainingStatusData") or {}
    if isinstance(latest_status, dict) and latest_status:
        device_data = next(iter(latest_status.values()))
        status_phrase = device_data.get("trainingStatusFeedbackPhrase")
        acute = device_data.get("acuteTrainingLoadDTO") or {}
        acwr_ratio = acute.get("dailyAcuteChronicWorkloadRatio")
        acwr_status = acute.get("acwrStatus")

    fitness_age_value = fitness_age.get("fitnessAge") if isinstance(fitness_age, dict) else None

    return {
        "date": cdate,
        "resting_hr": stats.get("restingHeartRate"),
        "hrv_overnight": last_night_hrv,
        "sleep_hours": (sleep_seconds / 3600) if sleep_seconds else None,
        "sleep_score": overall_score,
        "nap_minutes": (daily_sleep.get("napTimeSeconds") or 0) / 60 or None,
        "deep_sleep_h": (daily_sleep.get("deepSleepSeconds") / 3600) if daily_sleep.get("deepSleepSeconds") else None,
        "light_sleep_h": (daily_sleep.get("lightSleepSeconds") / 3600) if daily_sleep.get("lightSleepSeconds") else None,
        "rem_sleep_h": (daily_sleep.get("remSleepSeconds") / 3600) if daily_sleep.get("remSleepSeconds") else None,
        "awake_h": (daily_sleep.get("awakeSleepSeconds") / 3600) if daily_sleep.get("awakeSleepSeconds") else None,
        "avg_spo2": daily_sleep.get("avgSpO2"),
        "avg_respiration": daily_sleep.get("avgRespirationValue"),
        "heat_altitude_acclimation": heat_altitude,
        "body_battery_low": stats.get("bodyBatteryLowestValue"),
        "body_battery_high": stats.get("bodyBatteryHighestValue"),
        "avg_stress": avg_stress if (avg_stress is not None and avg_stress >= 0) else None,
        "steps": stats.get("totalSteps"),
        "training_readiness": readiness_score,
        "vo2max": vo2max,
        "race_5k_s": race.get("time5K"),
        "race_10k_s": race.get("time10K"),
        "race_half_s": race.get("timeHalfMarathon"),
        "race_marathon_s": race.get("timeMarathon"),
        "training_status": status_phrase,
        "acwr_ratio": acwr_ratio,
        "acwr_status": acwr_status,
        "fitness_age": fitness_age_value,
    }


def race_predictions_by_date(garmin: Garmin, start: str, end: str) -> dict:
    """Chunks into <=365-day windows since Garmin rejects longer ranges in one call."""
    start_d = datetime.strptime(start, "%Y-%m-%d").date()
    end_d = datetime.strptime(end, "%Y-%m-%d").date()

    result = {}
    chunk_start = start_d
    while chunk_start <= end_d:
        chunk_end = min(chunk_start + timedelta(days=365), end_d)
        rows = safe(lambda: garmin.get_race_predictions(
            startdate=chunk_start.isoformat(), enddate=chunk_end.isoformat(), _type="daily"
        )) or []
        for row in rows:
            if row.get("calendarDate"):
                result[row["calendarDate"]] = row
        chunk_start = chunk_end + timedelta(days=1)
    return result


def render_wellness_note(f: dict) -> str:
    lines = [f"# Garmin wellness {f['date']}", ""]

    if f["resting_hr"] is not None:
        lines.append(f"- Resting HR: {f['resting_hr']} bpm")
    if f["hrv_overnight"] is not None:
        lines.append(f"- HRV (overnight): {f['hrv_overnight']:.0f} ms")
    if f["sleep_hours"]:
        score_str = f" (score {f['sleep_score']})" if f["sleep_score"] is not None else ""
        lines.append(f"- Sleep: {f['sleep_hours']:.1f} h{score_str}")
    if f.get("deep_sleep_h") or f.get("light_sleep_h") or f.get("rem_sleep_h"):
        lines.append(
            f"- Sleep stages: deep {f.get('deep_sleep_h') or 0:.1f}h, "
            f"light {f.get('light_sleep_h') or 0:.1f}h, rem {f.get('rem_sleep_h') or 0:.1f}h, "
            f"awake {f.get('awake_h') or 0:.1f}h"
        )
    if f.get("nap_minutes"):
        lines.append(f"- Nap: {f['nap_minutes']:.0f} min")
    if f.get("avg_spo2") is not None:
        lines.append(f"- Avg SpO2: {f['avg_spo2']}%")
    if f.get("avg_respiration") is not None:
        lines.append(f"- Avg respiration: {f['avg_respiration']:.1f} breaths/min")
    if f.get("heat_altitude_acclimation") is not None:
        lines.append(f"- Heat/altitude acclimation: {f['heat_altitude_acclimation']}")
    if f["body_battery_low"] is not None and f["body_battery_high"] is not None:
        lines.append(f"- Body battery: {f['body_battery_low']} -> {f['body_battery_high']}")
    if f["avg_stress"] is not None:
        lines.append(f"- Stress (avg): {f['avg_stress']}")
    if f["steps"] is not None:
        lines.append(f"- Steps: {f['steps']}")
    if f["training_readiness"] is not None:
        lines.append(f"- Training readiness: {f['training_readiness']}")
    if f["vo2max"] is not None:
        lines.append(f"- VO2 max: {f['vo2max']}")
    if f.get("training_status"):
        lines.append(f"- Training status: {f['training_status'].replace('_', ' ').title()}")
    if f.get("acwr_ratio") is not None:
        lines.append(f"- Acute:chronic workload ratio: {f['acwr_ratio']:.2f} ({f.get('acwr_status')})")
    if f.get("fitness_age") is not None:
        lines.append(f"- Fitness age: {f['fitness_age']}")
    if f["race_marathon_s"] is not None:
        lines.append(
            f"- Predicted race times: 5K {fmt_race(f['race_5k_s'])}, "
            f"10K {fmt_race(f['race_10k_s'])}, Half {fmt_race(f['race_half_s'])}, "
            f"Marathon {fmt_race(f['race_marathon_s'])}"
        )

    if len(lines) == 2:
        lines.append("- (No wellness data synced for this day)")

    return "\n".join(lines) + "\n"


def fmt_race(seconds) -> str:
    if seconds is None:
        return "-"
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


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
        "min_elevation_m": act.get("minElevation"),
        "max_elevation_m": act.get("maxElevation"),
        "avg_elevation_m": act.get("avgElevation"),
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
    if f.get("avg_elevation_m") is not None:
        lines.append(f"- Avg elevation: {f['avg_elevation_m']:.0f} m")
    if f["avg_hr"]:
        lines.append(f"- Avg HR: {f['avg_hr']:.0f} bpm")
    if f["calories"]:
        lines.append(f"- Calories: {f['calories']:.0f}")

    return "\n".join(lines) + "\n"


def profile_fields(garmin: Garmin) -> dict:
    """One-time-per-sync facts: lactate threshold, gear, weekly stress rollup, lifetime count."""
    profile = safe(lambda: garmin.get_user_profile()) or {}
    user_data = profile.get("userData") or {}
    lactate_threshold_hr = user_data.get("lactateThresholdHeartRate")

    gear = []
    user_id = profile.get("id")
    if user_id:
        gear_list = safe(lambda: garmin.get_gear(str(user_id))) or []
        for item in gear_list:
            uuid = item.get("uuid")
            stats = (safe(lambda: garmin.get_gear_stats(uuid)) or {}) if uuid else {}
            gear.append({
                "name": item.get("displayName") or item.get("customMakeModel") or "Gear",
                "type": item.get("gearTypeName"),
                "status": item.get("gearStatusName"),
                "total_distance_m": stats.get("totalDistance"),
                "total_activities": stats.get("totalActivities"),
            })

    weekly_stress_rows = safe(lambda: garmin.get_weekly_stress(date.today().isoformat(), weeks=80)) or []
    weekly_stress = {row["calendarDate"]: row.get("value") for row in weekly_stress_rows if row.get("calendarDate")}

    lifetime_activity_count = safe(lambda: garmin.count_activities())

    return {
        "lactate_threshold_hr": lactate_threshold_hr,
        "gear": gear,
        "weekly_stress": weekly_stress,
        "lifetime_activity_count": lifetime_activity_count,
    }


def sync(garmin: Garmin, days: int, out_dir: str, dry_run: bool) -> None:
    out = Path(out_dir)
    today = date.today()

    range_start = (today - timedelta(days=days - 1)).isoformat()
    race_by_date = race_predictions_by_date(garmin, range_start, today.isoformat())

    wellness = []
    for i in range(days):
        day = today - timedelta(days=i)
        fields = wellness_fields(garmin, day, race_by_date)
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

    profile = profile_fields(garmin)

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
    existing["profile"] = profile

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
