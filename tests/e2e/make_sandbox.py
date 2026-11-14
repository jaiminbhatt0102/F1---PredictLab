import sys, json, pathlib, shutil
sys.path.insert(0,'/home/claude/repo/f1-predictlab')
import pandas as pd
from tests.conftest import build_root
root=pathlib.Path('/tmp/sbx'); shutil.rmtree(root,ignore_errors=True); root.mkdir()
build_root(root, drop_race=[17] if len(sys.argv)>1 and sys.argv[1]=='dropped' else [])
# a hand-made earlier prediction for round 16 so History can compare it with the real round 16 result
stored=pd.read_csv('/home/claude/repo/f1-predictlab/reports/upcoming_race_predictions.csv')
rows=[{"driver_id":r.driver_id,"driver_code":r.driver_code,"driver_name":f"{r.driver_given_name} {r.driver_family_name}","constructor_name":r.constructor_name,"grid":r.grid,"qualifying_position":r.qualifying_position,"sprint_position":None,"win_probability":r.target_win_probability,"win_rank":int(r.target_win_rank),"podium_probability":r.target_podium_probability,"podium_rank":int(r.target_podium_rank)} for r in stored.itertuples()]
ev=json.loads(pd.read_csv(root/'data/processed/f1_session_schedule.csv').query('season==2026 and round==16').to_json(orient='records'))[0]
snap={"snapshot_id":"2026-r16-race-post_qualifying-p-20261001T000000Z-demo","schema_version":1,"status":"ready","kind":"production","created_at_utc":"2026-10-01T10:00:00+00:00","trigger":"automatic",
 "requested":{"season":2026,"round":16,"session":"race","checkpoint":"post_qualifying","use_weather":False},"event_name":ev["race_name"],"event":None,
 "stage":{"checkpoint":"post_qualifying","label":"After qualifying","uses":"This weekend’s qualifying (and sprint) results plus earlier races."},
 "output_type":"win_and_podium_probability","output_label":"Chance of winning and of finishing on the podium","model":{"status":"production"},
 "inputs":{"grid_source":"qualifying_order","weather":{"available":False}},"input_availability":[],"warnings":["These are probabilities, not certainties."],"rows":rows}
(root/'data/predictions').mkdir(parents=True); (root/'data/predictions'/(snap["snapshot_id"]+'.json')).write_text(json.dumps(snap))
print('sandbox ready')
