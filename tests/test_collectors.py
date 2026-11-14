from src.data.collectors import _race_table


def test_race_table_normalizes_results():
    payload = {
        "MRData": {
            "RaceTable": {
                "Races": [{
                    "season": "2024", "round": "1", "raceName": "Test GP", "date": "2024-03-01",
                    "Circuit": {"circuitId": "test", "circuitName": "Test Circuit"},
                    "Results": [{
                        "Driver": {"driverId": "driver1", "code": "D01", "givenName": "Example", "familyName": "Driver"},
                        "Constructor": {"constructorId": "team1", "name": "Team"},
                        "grid": "1", "position": "1", "positionText": "1", "points": "25", "status": "Finished",
                        "Time": {"time": "1:30:00.000", "millis": "5400000"},
                        "FastestLap": {"rank": "1", "lap": "10", "Time": {"time": "1:20.000"}}
                    }]
                }]
            }
        }
    }
    rows = _race_table(payload, "Results")
    assert len(rows) == 1
    assert rows[0]["driver_id"] == "driver1"
    assert rows[0]["season"] == "2024"
    assert rows[0]["position"] == "1"
    assert rows[0]["fastest_lap_time"] == "1:20.000"
