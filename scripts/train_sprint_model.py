"""CLI wrapper: python scripts/train_sprint_model.py"""
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.models.train_sprint import train_sprint_model


def main() -> None:
    report = train_sprint_model()
    print(f"Sprint model: {report['selected_model']} | holdout {report['holdout_season']} | rows {report['training_rows']}")


if __name__ == "__main__":
    main()
