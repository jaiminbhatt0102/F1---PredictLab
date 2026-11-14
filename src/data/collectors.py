"""Download historical F1 result tables from the Jolpica-compatible Ergast API.

This module uses bounded HTTP requests, retries, caching, and explicit metadata.
It does not claim to collect timing/telemetry; that is a later FastF1 stage.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

BASE_URL = "https://api.jolpi.ca/ergast/f1"
DEFAULT_CACHE = Path(os.getenv("DATA_CACHE_DIR", "data/cache"))
DEFAULT_RAW = Path("data/raw")
TIMEOUT = httpx.Timeout(20.0, connect=8.0)
USER_AGENT = "F1-PredictLab/0.1 (historical research; respectful API access)"


@dataclass
class FetchRecord:
    endpoint: str
    status: str
    rows: int
    cache_path: str | None
    fetched_at: str | None
    message: str | None = None


def _safe_name(endpoint: str) -> str:
    return endpoint.strip("/").replace("/", "__").replace("?", "__").replace("=", "_")



def fetch_json(
    endpoint: str,
    *,
    cache_dir: Path = DEFAULT_CACHE,
    refresh: bool = False,
) -> dict[str, Any]:
    """Fetch an API endpoint with caching and rate-limit-aware retries."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{_safe_name(endpoint)}.json"

    if cache_path.exists() and not refresh:
        return json.loads(cache_path.read_text(encoding="utf-8"))

    url = f"{BASE_URL}/{endpoint.lstrip('/')}"
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    last_error: Exception | None = None
    max_attempts = 6

    with httpx.Client(
        timeout=TIMEOUT,
        follow_redirects=True,
        headers=headers,
    ) as client:
        for attempt in range(max_attempts):
            try:
                response = client.get(url)

                if response.status_code == 429:
                    last_error = httpx.HTTPStatusError(
                        "API rate limit exceeded (HTTP 429)",
                        request=response.request,
                        response=response,
                    )

                    if attempt < max_attempts - 1:
                        retry_after = response.headers.get("Retry-After")
                        try:
                            delay = float(retry_after) if retry_after else 5 * (2 ** attempt)
                        except ValueError:
                            delay = 5 * (2 ** attempt)

                        delay = min(max(delay, 1), 120)
                        print(
                            f"Rate limited by Jolpica. "
                            f"Waiting {delay:.0f}s before retry "
                            f"{attempt + 2}/{max_attempts}..."
                        )
                        time.sleep(delay)
                        continue

                    break

                response.raise_for_status()
                payload = response.json()

                if not isinstance(payload, dict):
                    raise ValueError("Provider returned a non-object JSON response")

                encoded = json.dumps(
                    payload, separators=(",", ":")
                ).encode("utf-8")

                if len(encoded) > 25_000_000:
                    raise ValueError("Response exceeded the 25 MB safety limit")

                cache_path.write_text(
                    json.dumps(payload, ensure_ascii=False),
                    encoding="utf-8",
                )

                meta = {
                    "endpoint": endpoint,
                    "url": url,
                    "sha256": hashlib.sha256(encoded).hexdigest(),
                    "fetched_at_epoch": time.time(),
                    "bytes": len(encoded),
                }
                cache_path.with_suffix(".meta.json").write_text(
                    json.dumps(meta, indent=2),
                    encoding="utf-8",
                )
                return payload

            except httpx.HTTPStatusError as exc:
                last_error = exc

                # Retrying other client errors (except 429) won't usually help.
                if exc.response.status_code < 500:
                    raise RuntimeError(
                        f"Could not fetch {endpoint}: {exc}"
                    ) from exc

            except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
                last_error = exc

            if attempt < max_attempts - 1:
                delay = min(2 ** (attempt + 1), 30)
                print(
                    f"Request failed: {last_error}. "
                    f"Retrying in {delay}s..."
                )
                time.sleep(delay)

    raise RuntimeError(
        f"Could not fetch {endpoint} after {max_attempts} attempts: {last_error}"
    ) from last_error

def _mrdata(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return payload["MRData"]
    except (KeyError, TypeError) as exc:
        raise ValueError("Unexpected API response: MRData missing") from exc


def _race_table(payload: dict[str, Any], result_key: str) -> list[dict[str, Any]]:
    mr = _mrdata(payload)
    race_table = mr.get("RaceTable", {})
    rows: list[dict[str, Any]] = []
    for race in race_table.get("Races", []):
        base = {
            "season": race.get("season"),
            "round": race.get("round"),
            "race_name": race.get("raceName"),
            "race_date": race.get("date"),
            "circuit_id": (race.get("Circuit") or {}).get("circuitId"),
            "circuit_name": (race.get("Circuit") or {}).get("circuitName"),
        }
        for result in race.get(result_key, []):
            driver = result.get("Driver") or {}
            constructor = result.get("Constructor") or {}
            time_data = result.get("Time") or {}
            fastest = result.get("FastestLap") or {}
            rows.append({
                **base,
                "driver_id": driver.get("driverId"),
                "driver_code": driver.get("code"),
                "driver_number": driver.get("permanentNumber"),
                "driver_given_name": driver.get("givenName"),
                "driver_family_name": driver.get("familyName"),
                "constructor_id": constructor.get("constructorId"),
                "constructor_name": constructor.get("name"),
                "grid": result.get("grid"),
                "position": result.get("position"),
                "position_text": result.get("positionText"),
                "points": result.get("points"),
                "status": result.get("status"),
                "time": time_data.get("time"),
                "milliseconds": time_data.get("millis"),
                "fastest_lap_rank": fastest.get("rank"),
                "fastest_lap_number": fastest.get("lap"),
                "fastest_lap_time": (fastest.get("Time") or {}).get("time"),
                # Qualifying lap times (only present for qualifying results; None for races).
                "q1": result.get("Q1"),
                "q2": result.get("Q2"),
                "q3": result.get("Q3"),
            })
    return rows


def collect_season_results(season: int, *, refresh: bool = False) -> dict[str, Any]:
    """Collect race and qualifying results for one season, paginating API responses."""
    if season < 1950 or season > 2100:
        raise ValueError("season must be between 1950 and 2100")
    all_rows: dict[str, list[dict[str, Any]]] = {"race": [], "qualifying": []}
    endpoints = {"race": f"{season}/results", "qualifying": f"{season}/qualifying"}
    reports: list[dict[str, Any]] = []
    for session, base_endpoint in endpoints.items():
        offset = 0
        while True:
            endpoint = f"{base_endpoint}?limit=100&offset={offset}"
            payload = fetch_json(endpoint, refresh=refresh)
            mr = _mrdata(payload)
            rows = _race_table(payload, "Results" if session == "race" else "QualifyingResults")
            all_rows[session].extend(rows)
            total = int(mr.get("total", len(rows)))
            reports.append({
                "endpoint": endpoint,
                "status": "ok",
                "rows_returned": len(rows),
                "total_reported": total,
                "offset": offset,
            })
            offset += int(mr.get("limit", 100))
            if offset >= total or not rows:
                break
    return {"season": season, "tables": all_rows, "requests": reports}


def collect_season_sprints(season: int, *, refresh: bool = False) -> dict[str, Any]:
    """Collect sprint results; older/newer provider coverage may differ."""
    endpoint_base = f"{season}/sprint"
    offset = 0
    rows: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []
    while True:
        endpoint = f"{endpoint_base}?limit=100&offset={offset}"
        payload = fetch_json(endpoint, refresh=refresh)
        mr = _mrdata(payload)
        page_rows = _race_table(payload, "SprintResults")
        rows.extend(page_rows)
        total = int(mr.get("total", len(page_rows)))
        reports.append({"endpoint": endpoint, "status": "ok", "rows_returned": len(page_rows), "total_reported": total})
        offset += int(mr.get("limit", 100))
        if offset >= total or not page_rows:
            break
    return {"season": season, "tables": {"sprint": rows}, "requests": reports}


def _session_utc(block: Any) -> str | None:
    """Combine the source's separate date and time fields into one UTC ISO timestamp."""
    if not isinstance(block, dict) or not block.get("date") or not block.get("time"):
        return None
    time = str(block["time"]).replace("Z", "")
    return f"{block['date']}T{time}+00:00"


def collect_calendar(season: int, *, refresh: bool = False) -> dict[str, Any]:
    payload = fetch_json(f"{season}.json?limit=100", refresh=refresh)
    mr = _mrdata(payload)
    races = mr.get("RaceTable", {}).get("Races", [])
    return {
        "season": season,
        "events": [
            {
                "season": race.get("season"),
                "round": race.get("round"),
                "race_name": race.get("raceName"),
                "race_date": race.get("date"),
                "circuit_id": (race.get("Circuit") or {}).get("circuitId"),
                "circuit_name": (race.get("Circuit") or {}).get("circuitName"),
                "country": ((race.get("Circuit") or {}).get("Location") or {}).get("country"),
                "locality": ((race.get("Circuit") or {}).get("Location") or {}).get("locality"),
                "url": race.get("url"),
                "first_practice_utc": _session_utc(race.get("FirstPractice")),
                "sprint_qualifying_utc": _session_utc(race.get("SprintQualifying") or race.get("SprintShootout")),
                "sprint_utc": _session_utc(race.get("Sprint")),
                "qualifying_utc": _session_utc(race.get("Qualifying")),
            }
            for race in races
        ],
        "total_reported": int(mr.get("total", len(races))),
    }


def save_season_bundle(bundle: dict[str, Any], *, output_dir: Path = DEFAULT_RAW) -> list[str]:
    """Save normalized session tables as CSV plus a JSON collection report."""
    import pandas as pd

    output_dir.mkdir(parents=True, exist_ok=True)
    season = int(bundle["season"])
    paths: list[str] = []
    for session, rows in bundle["tables"].items():
        path = output_dir / f"{season}_{session}_results.csv"
        frame = pd.DataFrame(rows)
        frame.to_csv(path, index=False)
        paths.append(str(path))
    report_path = output_dir / f"{season}_collection_report.json"
    report_path.write_text(json.dumps({
        "season": season,
        "requests": bundle.get("requests", []),
        "row_counts": {key: len(value) for key, value in bundle["tables"].items()},
        "files": paths,
    }, indent=2), encoding="utf-8")
    paths.append(str(report_path))
    return paths
