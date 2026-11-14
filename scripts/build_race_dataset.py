from __future__ import annotations
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from src.features.build_dataset import write_race_training_table

def main() -> None:
    output = write_race_training_table()
    print(f"Race training table written to: {output}")
    import pandas as pd
    frame = pd.read_csv(output)
    print(f"Rows: {len(frame):,}; columns: {len(frame.columns)}")
    if not frame.empty:
        print(f"Seasons: {frame['season'].min()}–{frame['season'].max()}")
        print(f"Events: {frame[['season', 'round']].drop_duplicates().shape[0]}")
        print(f"Drivers: {frame['driver_id'].nunique()}")
        print(f"Win labels: {int(frame['target_win'].sum())}")
        print(f"Podium labels: {int(frame['target_podium'].sum())}")

if __name__ == "__main__":
    main()
