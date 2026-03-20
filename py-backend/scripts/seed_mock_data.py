from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.db import Appointment, Base, DoctorSchedule, SessionLocal, User, engine, init_db


DEPARTMENT_DOCTORS: dict[str, list[str]] = {
    "神经内科": ["朱以诚", "崔丽英", "韩启明", "顾亦凡"],
    "心内科": ["梁晨", "傅静", "赵其安", "宋启文"],
    "呼吸与危重症医学科": ["陈听雨", "白知远", "何泽坤", "唐予安"],
    "消化内科": ["陆景行", "方嘉宁", "高若川", "郑楚宁"],
    "内分泌科": ["周璟", "沈清和", "尹芷若", "严思远"],
    "肾内科": ["罗怀瑾", "许望舒", "段明哲", "丁婧"],
    "血液内科": ["蒋闻舟", "邓宜宁", "贺修远", "谭雁秋"],
    "感染科": ["苏彦廷", "温知行", "熊若岚", "叶承宇"],
    "普通外科": ["潘景程", "裴昭", "黎砚舟", "孔南乔"],
    "骨科": ["石承恩", "姚景煜", "任骁", "韩知予"],
    "妇科": ["林若岚", "丁可心", "徐清妍", "姜雅宁"],
    "儿科": ["顾青禾", "许泽言", "周安宁", "章洛"],
    "口腔科": ["万阔", "吴清越", "钟嘉言", "袁知微"],
    "眼科": ["秦屿", "唐知夏", "沈慕白", "欧阳岚"],
    "耳鼻喉科": ["季闻笙", "彭景初", "卢青筠", "汪以宁"],
}

TIME_OF_DAY = ("上午", "下午")


def build_users(total: int = 120) -> list[dict[str, Any]]:
    users: list[dict[str, Any]] = []
    for i in range(total):
        users.append(
            {
                "name": f"测试用户{i + 1:03d}",
                "id_card": f"9900001990{(i % 12) + 1:02d}{(i % 28) + 1:02d}{i:04d}",
                "gender": "男" if i % 2 == 0 else "女",
                "age": 18 + (i % 60),
            }
        )
    return users


def build_schedules(days: int = 30) -> tuple[list[dict[str, Any]], list[int]]:
    now = datetime.now()
    schedules: list[dict[str, Any]] = []
    booking_plan: list[int] = []

    for day_offset in range(1, days + 1):
        schedule_date = (now + timedelta(days=day_offset)).strftime("%Y-%m-%d")
        for department, doctors in DEPARTMENT_DOCTORS.items():
            for doctor_index, doctor_name in enumerate(doctors):
                for slot_index, time_of_day in enumerate(TIME_OF_DAY):
                    total_slots = 20 + ((day_offset + doctor_index + slot_index) % 16)
                    is_stopped = (day_offset + doctor_index + slot_index) % 23 == 0
                    booked_slots = 0 if is_stopped else (day_offset + doctor_index + slot_index) % 6

                    schedules.append(
                        {
                            "doctor_name": doctor_name,
                            "department": department,
                            "schedule_date": schedule_date,
                            "time_of_day": time_of_day,
                            "total_slots": total_slots,
                            "available_slots": total_slots - booked_slots,
                            "status": "STOPPED" if is_stopped else "ACTIVE",
                            "stop_reason": "学术会议停诊" if is_stopped else None,
                        }
                    )
                    booking_plan.append(booked_slots)

    return schedules, booking_plan


def build_mock_appointments(
    users: list[dict[str, Any]],
    schedules: list[dict[str, Any]],
    booking_plan: list[int],
) -> list[dict[str, Any]]:
    appointments: list[dict[str, Any]] = []
    user_index = 0

    for schedule, booked_slots in zip(schedules, booking_plan):
        if schedule["status"] != "ACTIVE" or booked_slots <= 0:
            continue

        for _ in range(booked_slots):
            user = users[user_index % len(users)]
            appointment_date = schedule["schedule_date"]
            time_of_day = schedule["time_of_day"]
            doctor_name = schedule["doctor_name"]

            appointments.append(
                {
                    "id_card": user["id_card"],
                    "patient_name": user["name"],
                    "department": schedule["department"],
                    "doctor_name": doctor_name,
                    "appointment_date": appointment_date,
                    "time_of_day": time_of_day,
                    "appointment_time": f"{appointment_date}-{time_of_day}",
                    "status": "BOOKED",
                    "note": f"doctor={doctor_name}",
                }
            )
            user_index += 1

    return appointments


def seed() -> None:
    # 开发阶段便于快速迁移：先清空再重建
    Base.metadata.drop_all(bind=engine)
    init_db()

    users = build_users(total=120)
    schedules, booking_plan = build_schedules(days=30)
    mock_appointments = build_mock_appointments(users, schedules, booking_plan)

    with SessionLocal() as session:
        user_by_id_card: dict[str, User] = {}
        for row in users:
            u = User(**row)
            session.add(u)
            session.flush()
            user_by_id_card[u.id_card] = u

        for row in schedules:
            session.add(DoctorSchedule(**row))

        for row in mock_appointments:
            user = user_by_id_card[row["id_card"]]
            session.add(Appointment(user_id=user.id, **row))

        session.commit()
        user_total = session.query(User).count()
        schedule_total = session.query(DoctorSchedule).count()
        appointment_total = session.query(Appointment).count()
        print(
            "Seed complete: "
            f"users={user_total}, schedules={schedule_total}, appointments={appointment_total}"
        )


if __name__ == "__main__":
    seed()
