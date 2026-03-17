from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from scripts.seed_mock_data import seed


def main() -> None:
    seed()
    client = TestClient(app)

    r1 = client.get("/schedules")
    print("GET /schedules =>", r1.status_code, "count=", len(r1.json()))

    payload = {
        "doctor_name": "测试医生A",
        "department": "神经内科",
        "schedule_date": "2026-03-21",
        "time_of_day": "上午",
        "total_slots": 10,
        "available_slots": 10,
    }
    r2 = client.post("/schedules", json=payload)
    print("POST /schedules =>", r2.status_code, r2.json())
    schedule_id = r2.json().get("id")

    r3 = client.put(f"/schedules/{schedule_id}/stop", json={"reason": "临时停诊"})
    print("PUT /schedules/{id}/stop =>", r3.status_code, r3.json())

    r4 = client.put(
        f"/schedules/{schedule_id}/slots",
        json={"total_slots": 12, "available_slots": 8},
    )
    print("PUT /schedules/{id}/slots =>", r4.status_code, r4.json())

    r5 = client.get("/schedules", params={"schedule_date": "2026-03-21"})
    print("GET verify =>", r5.status_code, r5.json())


if __name__ == "__main__":
    main()
