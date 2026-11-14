
"""Train and evaluate baseline F1 prediction models."""
from pathlib import Path
import sys

# Ensure the project root is available for imports.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.models.train_baselines import train_and_evaluate


def main():
    train_and_evaluate()


if __name__ == "__main__":
    main()
