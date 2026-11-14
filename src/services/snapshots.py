"""Immutable prediction snapshots.

Each generated prediction is written once to its own JSON file. Files are created
with exclusive mode, never edited, and never deleted by the application. A new
prediction always creates a new snapshot.
"""
from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.services import data_service as ds

_ID = re.compile(r"^[A-Za-z0-9_.-]{8,120}$")


def _dir() -> Path:
    return ds.ROOT / "data" / "predictions"


def new_id(season: int, round_no: int, session: str, checkpoint: str, experimental: bool) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    kind = "x" if experimental else "p"
    return f"{season}-r{round_no:02d}-{session}-{checkpoint}-{kind}-{stamp}-{secrets.token_hex(2)}"


def save(snapshot: dict[str, Any]) -> dict[str, Any]:
    snap_id = snapshot["snapshot_id"]
    if not _ID.match(snap_id):
        raise ds.ServiceError("invalid_snapshot", "The prediction could not be saved.", 500)
    folder = _dir()
    folder.mkdir(parents=True, exist_ok=True)
    try:
        with open(folder / f"{snap_id}.json", "x", encoding="utf-8") as handle:
            json.dump(snapshot, handle, indent=2)
    except FileExistsError as exc:
        raise ds.ServiceError("snapshot_exists", "A prediction with that ID already exists and cannot be replaced.", 409) from exc
    except OSError as exc:
        raise ds.ServiceError("snapshot_not_saved", "The prediction was made but could not be saved on disk.", 503) from exc
    return snapshot


def get(snapshot_id: str) -> dict[str, Any]:
    if not _ID.match(snapshot_id):
        raise ds.ServiceError("invalid_snapshot", "That is not a valid prediction ID.", 422)
    path = _dir() / f"{snapshot_id}.json"
    if not path.exists():
        raise ds.ServiceError("snapshot_not_found", "That saved prediction does not exist.", 404)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ds.ServiceError("snapshot_unreadable", "That saved prediction is damaged and cannot be shown.", 503) from exc


def _summary(snap: dict[str, Any]) -> dict[str, Any]:
    keys = ["snapshot_id", "created_at_utc", "trigger", "kind", "requested", "event_name", "stage", "output_type", "model"]
    out = {k: snap.get(k) for k in keys}
    rows = snap.get("rows") or []
    if snap.get("output_type") == "win_and_podium_probability" and rows:
        top = max(rows, key=lambda r: r.get("win_probability") or 0)
        out["headline"] = {"driver_name": top.get("driver_name"), "win_probability": top.get("win_probability")}
    elif rows:
        out["headline"] = {"driver_name": rows[0].get("driver_name"), "win_probability": None}
    return out


def list_snapshots(season: int | None = None, round_no: int | None = None, session: str | None = None,
                   kind: str | None = None, limit: int = 30, offset: int = 0) -> dict[str, Any]:
    folder = _dir()
    items: list[dict[str, Any]] = []
    if folder.exists():
        for path in folder.glob("*.json"):
            try:
                snap = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue  # a damaged file must not hide the others
            req = snap.get("requested", {})
            if season is not None and req.get("season") != season:
                continue
            if round_no is not None and req.get("round") != round_no:
                continue
            if session is not None and req.get("session") != session:
                continue
            if kind is not None and snap.get("kind") != kind:
                continue
            items.append(_summary(snap))
    items.sort(key=lambda s: s.get("created_at_utc") or "", reverse=True)
    return {"total": len(items), "limit": limit, "offset": offset, "items": items[offset: offset + limit]}


def latest_for(season: int, round_no: int, session: str, checkpoint: str, experimental: bool = False) -> dict[str, Any] | None:
    found = list_snapshots(season, round_no, session, "experimental" if experimental else "production", limit=500)["items"]
    for item in found:
        if (item.get("requested") or {}).get("checkpoint") == checkpoint:
            return item
    return None


# ----------------------------------------------------------------- comparison
def compare_with_results(snap: dict[str, Any]) -> dict[str, Any] | None:
    """Compare a saved prediction with the real result, once that result exists."""
    req = snap["requested"]
    try:
        sessions = ds.get_sessions(req["season"], req["round"])["sessions"]
    except ds.ServiceError:
        return None
    block = sessions.get(req["session"])
    if not block or block["status"] != "complete":
        return None
    actual = {r["driver_code"]: r["position"] for r in block["rows"] if r.get("driver_code") and r.get("position") is not None}
    rows = snap.get("rows") or []
    if not actual or not rows:
        return None
    if snap.get("output_type") == "win_and_podium_probability":
        ranked = sorted(rows, key=lambda r: (-(r.get("win_probability") or 0), r.get("driver_name") or ""))
        picked = [r for r in ranked if r.get("driver_code") in actual]
        top3 = {r["driver_code"] for r in sorted(rows, key=lambda r: -(r.get("podium_probability") or 0))[:3]}
        real_podium = {c for c, p in actual.items() if p <= 3}
        winner = next((c for c, p in actual.items() if p == 1), None)
        predicted_winner = picked[0] if picked else None
        table = [{"driver_code": r["driver_code"], "driver_name": r["driver_name"], "predicted_rank": i + 1, "actual_position": actual.get(r["driver_code"]),
                  "win_probability": r.get("win_probability"), "podium_probability": r.get("podium_probability")} for i, r in enumerate(picked)]
        return {
            "kind": "race",
            "headline": {
                "predicted_winner": predicted_winner["driver_name"] if predicted_winner else None,
                "actual_winner": next((r["driver_name"] for r in rows if r.get("driver_code") == winner), winner),
                "winner_correct": bool(predicted_winner and predicted_winner["driver_code"] == winner),
                "podium_hits": len(top3 & real_podium),
                "podium_picks": len(top3),
            },
            "rows": table,
        }
    table = []
    for r in sorted(rows, key=lambda r: r.get("predicted_order") or 0):
        a = actual.get(r.get("driver_code"))
        table.append({"driver_code": r.get("driver_code"), "driver_name": r.get("driver_name"), "predicted_rank": r.get("predicted_order"), "actual_position": a,
                      "places_off": None if a is None else int(abs(a - r["predicted_order"]))})
    off = [t["places_off"] for t in table if t["places_off"] is not None]
    top3_pred = {t["driver_code"] for t in table[:3]}
    top3_real = {c for c, p in actual.items() if p <= 3}
    return {
        "kind": req["session"],
        "headline": {
            "average_places_off": round(sum(off) / len(off), 1) if off else None,
            "exact_matches": sum(1 for o in off if o == 0),
            "drivers_compared": len(off),
            "top3_hits": len(top3_pred & top3_real),
        },
        "rows": table,
    }


def track_record() -> dict[str, Any]:
    """How saved production predictions turned out, counting each stage of each event once."""
    items = list_snapshots(kind="production", limit=1000)["items"]
    seen: set[tuple] = set()
    race = {"compared": 0, "winner_correct": 0, "podium_hits": 0, "podium_picks": 0}
    order = {"qualifying": {"compared": 0, "off": [], "exact": 0, "drivers": 0}, "sprint": {"compared": 0, "off": [], "exact": 0, "drivers": 0}}
    for item in items:  # newest first, so the latest prediction per stage is the one counted
        req = item["requested"]
        key = (req["season"], req["round"], req["session"], req["checkpoint"])
        if key in seen:
            continue
        seen.add(key)
        try:
            cmp = compare_with_results(get(item["snapshot_id"]))
        except ds.ServiceError:
            continue
        if not cmp:
            continue
        h = cmp["headline"]
        if cmp["kind"] == "race":
            race["compared"] += 1
            race["winner_correct"] += 1 if h["winner_correct"] else 0
            race["podium_hits"] += h["podium_hits"]
            race["podium_picks"] += h["podium_picks"]
        elif cmp["kind"] in order and h.get("average_places_off") is not None:
            o = order[cmp["kind"]]
            o["compared"] += 1
            o["off"].append(h["average_places_off"])
            o["exact"] += h["exact_matches"]
            o["drivers"] += h["drivers_compared"]
    def summary(o: dict) -> dict:
        return {"compared": o["compared"], "average_places_off": round(sum(o["off"]) / len(o["off"]), 1) if o["off"] else None,
                "exact_matches": o["exact"], "drivers_compared": o["drivers"]}
    return {"race": race, "qualifying": summary(order["qualifying"]), "sprint": summary(order["sprint"])}
