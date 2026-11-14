import shutil
from pathlib import Path

import pandas as pd
import pytest

from src.services import data_service as ds

REAL = Path(__file__).resolve().parents[1]


def build_root(tmp: Path, drop_race=(), drop_sprint=(), drop_qual=()) -> Path:
    """A throwaway project root: small data copied, big model folder linked read-only."""
    for sub in ("data/processed", "data/features", "data/raw", "reports"):
        shutil.copytree(REAL / sub, tmp / sub)
    (tmp / "models").symlink_to(REAL / "models", target_is_directory=True)
    (tmp / "scripts").symlink_to(REAL / "scripts", target_is_directory=True)
    for session, rounds in (("race", drop_race), ("sprint", drop_sprint), ("qualifying", drop_qual)):
        if rounds:
            path = tmp / "data/processed" / f"2026_{session}_normalized.csv"
            frame = pd.read_csv(path)
            frame[~frame["round"].isin(rounds)].to_csv(path, index=False)
    return tmp


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Real data, but writes (snapshots, jobs, state) go to a temp folder."""
    root = build_root(tmp_path)
    monkeypatch.setattr(ds, "ROOT", root)
    return root


@pytest.fixture
def after_qualifying(tmp_path, monkeypatch):
    """Round 17: qualifying and sprint done, race not yet run."""
    root = build_root(tmp_path, drop_race=[17])
    monkeypatch.setattr(ds, "ROOT", root)
    return root


@pytest.fixture
def before_sprint(tmp_path, monkeypatch):
    """Round 17 with no sprint result and no race result yet."""
    root = build_root(tmp_path, drop_race=[17], drop_sprint=[17], drop_qual=[17])
    monkeypatch.setattr(ds, "ROOT", root)
    return root
