from pathlib import Path
import pandas as pd
import fastf1

OUTPUT = Path("data/processed/f1_session_schedule.csv")


def get_race_start(row):
    for i in range(1, 6):
        if str(row.get(f"Session{i}", "")).strip().casefold() == "race":
            return row.get(f"Session{i}DateUtc")
    return pd.NaT


def main():
    schedules = []

    for season in range(2018, 2027):
        print(f"Fetching {season} schedule...")
        schedule = fastf1.get_event_schedule(
            season, include_testing=False
        )

        schedule["season"] = season
        schedule["race_start_utc"] = schedule.apply(
            get_race_start, axis=1
        )
        schedules.append(schedule)

    result = pd.concat(schedules, ignore_index=True)

    result = result[result["RoundNumber"].gt(0)].copy()
    result["race_start_utc"] = pd.to_datetime(
        result["race_start_utc"], utc=True, errors="coerce"
    )

    result = result.rename(columns={
        "RoundNumber": "round",
        "EventName": "race_name",
        "Country": "country",
        "Location": "locality",
        "EventDate": "event_date",
        "EventFormat": "event_format",
    })

    columns = [
        "season", "round", "race_name", "country",
        "locality", "event_date", "event_format",
        "race_start_utc",
    ]
    result = result[columns].sort_values(
        ["season", "round"]
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUTPUT, index=False)

    print(f"\nSaved: {OUTPUT}")
    print("Total events:", len(result))
    print("Missing race start times:", result["race_start_utc"].isna().sum())
    print("\nEvents by season:")
    print(result.groupby("season").size().to_string())
    print("\nSample:")
    print(result.head(8).to_string(index=False))


if __name__ == "__main__":
    main()
