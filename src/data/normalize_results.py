
"""Normalize collected F1 result tables into consistent, typed datasets."""
from __future__ import annotations

from pathlib import Path
import pandas as pd


SESSION_COLUMNS = {
    "race": [
        "season", "round", "race_name", "race_date", "circuit_id",
        "circuit_name", "driver_id", "driver_code", "driver_given_name",
        "driver_family_name", "constructor_id", "constructor_name",
        "grid", "position", "position_text", "points", "status", "time",
        "milliseconds", "fastest_lap_rank", "fastest_lap_number",
        "fastest_lap_time",
    ],
    "qualifying": [
        "season", "round", "race_name", "race_date", "circuit_id",
        "circuit_name", "driver_id", "driver_code", "driver_number",
        "driver_given_name", "driver_family_name", "constructor_id",
        "constructor_name", "position", "q1", "q2", "q3",
    ],
    "sprint": [
        "season", "round", "race_name", "race_date", "circuit_id",
        "circuit_name", "driver_id", "driver_code", "driver_given_name",
        "driver_family_name", "constructor_id", "constructor_name",
        "grid", "position", "position_text", "points", "status", "time",
        "milliseconds", "fastest_lap_rank", "fastest_lap_number",
        "fastest_lap_time",
    ],
}

INTEGER_COLUMNS = [
    "season", "round", "grid", "position", "milliseconds",
    "fastest_lap_rank", "fastest_lap_number", "driver_number",
]

NUMERIC_COLUMNS = ["points"]

STRING_COLUMNS = [
    "race_name", "race_date", "circuit_id", "circuit_name",
    "driver_id", "driver_code", "driver_given_name",
    "driver_family_name", "constructor_id", "constructor_name",
    "position_text", "status", "time", "fastest_lap_time",
    "q1", "q2", "q3",
]


def _to_nullable_integer(series: pd.Series) -> pd.Series:
    """Convert numeric data to nullable integers without unsafe casts."""
    values = pd.to_numeric(series, errors="coerce")
    # Integer fields must be whole numbers. Invalid fractional values
    # are treated as missing instead of silently truncated.
    fractional = values.notna() & ((values % 1).abs() > 1e-9)
    values = values.mask(fractional, pd.NA)
    return values.astype("Int64")


def normalize_frame(frame: pd.DataFrame, session: str) -> pd.DataFrame:
    """Normalize one race, qualifying, or sprint result table."""
    if session not in SESSION_COLUMNS:
        raise ValueError(f"Unsupported session: {session}")

    frame = frame.copy()

    # Supply absent columns and enforce a stable schema.
    for column in SESSION_COLUMNS[session]:
        if column not in frame.columns:
            frame[column] = pd.NA

    frame = frame[SESSION_COLUMNS[session]]

    # Convert integer-valued fields safely, preserving missing values.
    for column in INTEGER_COLUMNS:
        if column in frame.columns:
            frame[column] = _to_nullable_integer(frame[column])

    # Points can be fractional in some data sources, so retain numeric type.
    if "points" in frame.columns:
        frame["points"] = pd.to_numeric(
            frame["points"], errors="coerce"
        ).astype("Float64")

    # IDs and descriptive fields should remain strings.
    for column in STRING_COLUMNS:
        if column in frame.columns:
            values = frame[column].astype("string").str.strip()
            frame[column] = values.replace(
                {"": pd.NA, r"\N": pd.NA, "nan": pd.NA}
            )

    # Stable event key, scoped by season.
    frame["event_key"] = (
        frame["season"].astype("string")
        + "-"
        + frame["round"].astype("string")
    )
    frame["session"] = session

    return frame


def normalize_directory(
    raw_dir: str | Path = "data/raw",
    output_dir: str | Path = "data/processed",
) -> list[Path]:
    """Normalize available result CSVs and return created output paths."""
    raw_dir = Path(raw_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not raw_dir.exists():
        raise FileNotFoundError(f"Raw data directory not found: {raw_dir}")

    outputs: list[Path] = []

    for path in sorted(raw_dir.glob("*_results.csv")):
        parts = path.stem.split("_")
        if len(parts) < 3:
            continue

        season, session = parts[0], parts[1]
        if session not in SESSION_COLUMNS:
            continue

        try:
            frame = pd.read_csv(
                path,
                dtype={
                    "driver_id": "string",
                    "constructor_id": "string",
                },
            )
        except pd.errors.EmptyDataError:
            print(f"Skipping empty CSV: {path}")
            continue

        if frame.empty:
            print(f"Skipping CSV with no rows: {path}")
            continue

        normalized = normalize_frame(frame, session)

        output = output_dir / f"{season}_{session}_normalized.csv"
        normalized.to_csv(output, index=False)
        outputs.append(output)

        print(
            f"Normalized {path.name}: "
            f"{len(normalized)} rows -> {output}"
        )

    if not outputs:
        print("Warning: no non-empty result files were normalized.")

    return outputs
