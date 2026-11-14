from __future__ import annotations
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from src.data.normalize_results import normalize_directory

def main() -> None:
    outputs = normalize_directory()
    print(f"Normalized {len(outputs)} session files:")
    for path in outputs:
        print(f"- {path}")

if __name__ == "__main__":
    main()
