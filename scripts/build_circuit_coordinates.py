from pathlib import Path
import sys

# Add the project root to Python's module search path.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from src.data.collectors import fetch_json

PROCESSED = PROJECT_ROOT / "data" / "processed"
OUTPUT = PROCESSED / "circuit_coordinates.csv"


def get_local_circuits():
    files = sorted(PROCESSED.glob("*_race_normalized.csv"))
    if not files:
        raise FileNotFoundError("No normalized race files found.")

    frames = []
    for path in files:
        frame = pd.read_csv(
            path,
            usecols=lambda col: col in ["circuit_id", "circuit_name"],
        )
        frames.append(frame)

    circuits = pd.concat(frames, ignore_index=True)
    circuits["circuit_id"] = circuits["circuit_id"].astype("string").str.strip()
    circuits = circuits.dropna(subset=["circuit_id"])
    circuits = circuits[circuits["circuit_id"] != ""]
    return circuits.drop_duplicates("circuit_id")


def get_api_circuits():
    rows = []
    offset = 0

    while True:
        payload = fetch_json(
            f"circuits.json?limit=100&offset={offset}"
        )
        metadata = payload.get("MRData", {})
        page = metadata.get("CircuitTable", {}).get("Circuits", [])
        rows.extend(page)

        total = int(metadata.get("total", len(rows)))
        limit = int(metadata.get("limit", 100))

        if not page or offset + limit >= total:
            break
        offset += limit

    records = []
    for item in rows:
        location = item.get("Location") or {}
        records.append({
            "circuit_id": item.get("circuitId"),
            "api_circuit_name": item.get("circuitName"),
            "latitude": pd.to_numeric(
                location.get("lat"), errors="coerce"
            ),
            "longitude": pd.to_numeric(
                location.get("long"), errors="coerce"
            ),
            "locality": location.get("locality"),
            "country": location.get("country"),
        })

    return pd.DataFrame(records).drop_duplicates("circuit_id")


def main():
    local = get_local_circuits()
    api = get_api_circuits()

    result = local.merge(
        api, on="circuit_id", how="left", validate="one_to_one"
    )

    valid_coordinates = (
        result["latitude"].between(-90, 90)
        & result["longitude"].between(-180, 180)
    )

    result["coordinate_source"] = result["latitude"].notna().map(
        {True: "Jolpica circuits API", False: pd.NA}
    )
    result["verified"] = valid_coordinates.fillna(False)

    unmatched = result.loc[
        ~result["verified"], "circuit_id"
    ].tolist()

    result = result[
        [
            "circuit_id",
            "circuit_name",
            "api_circuit_name",
            "latitude",
            "longitude",
            "locality",
            "country",
            "coordinate_source",
            "verified",
        ]
    ].sort_values("circuit_id")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUTPUT, index=False)

    matched = result["verified"].sum()
    unmatched = result.loc[~result["verified"], "circuit_id"].tolist()

    print(f"Saved: {OUTPUT}")
    print(f"Local circuits: {len(result)}")
    print(f"Valid coordinate matches: {matched}")
    print(f"Unmatched or invalid: {len(unmatched)}")

    if unmatched:
        print("Circuits requiring manual verification:")
        for circuit_id in unmatched:
            print(f"  - {circuit_id}")

    print("\nMapping preview:")
    print(result.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
