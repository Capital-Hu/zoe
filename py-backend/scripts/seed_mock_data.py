from __future__ import annotations

from datetime import datetime, timedelta

from app.db import Appointment, Base, DoctorSchedule, SessionLocal, User, engine, init_db


def seed() -> None:
    # 开发阶段便于快速迁移：先清空再重建
    Base.metadata.drop_all(bind=engine)
    init_db()

    now = datetime.now()
    date1 = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    date2 = (now + timedelta(days=2)).strftime("%Y-%m-%d")
    date3 = (now + timedelta(days=3)).strftime("%Y-%m-%d")

    users = [
        {"name": "张三", "id_card": "110101199001011234", "gender": "男", "age": 36},
        {"name": "李四", "id_card": "110101199202021111", "gender": "女", "age": 34},
        {"name": "王五", "id_card": "110101198812123333", "gender": "男", "age": 38},
        {"name": "赵六", "id_card": "110101199611221999", "gender": "女", "age": 30},
        {"name": "孙七", "id_card": "110101199903031888", "gender": "男", "age": 27},
    ]

    schedules = [
        {
            "doctor_name": "朱以诚",
            "department": "神经内科",
            "schedule_date": date1,
            "time_of_day": "上午",
            "total_slots": 20,
            "available_slots": 19,
            "status": "ACTIVE",
        },
        {
            "doctor_name": "崔丽英",
            "department": "神经内科",
            "schedule_date": date1,
            "time_of_day": "下午",
            "total_slots": 20,
            "available_slots": 20,
            "status": "ACTIVE",
        },
        {
            "doctor_name": "万阔",
            "department": "口腔科",
            "schedule_date": date1,
            "time_of_day": "下午",
            "total_slots": 20,
            "available_slots": 19,
            "status": "ACTIVE",
        },
        {
            "doctor_name": "心内科门诊A",
            "department": "心内科",
            "schedule_date": date2,
            "time_of_day": "上午",
            "total_slots": 20,
            "available_slots": 19,
            "status": "ACTIVE",
        },
        {
            "doctor_name": "呼吸内科门诊A",
            "department": "呼吸与危重症医学科",
            "schedule_date": date2,
            "time_of_day": "下午",
            "total_slots": 20,
            "available_slots": 19,
            "status": "ACTIVE",
        },
        {
            "doctor_name": "消化内科门诊A",
            "department": "消化内科",
            "schedule_date": date3,
            "time_of_day": "上午",
            "total_slots": 20,
            "available_slots": 19,
            "status": "ACTIVE",
        },
    ]

    mock_appointments = [
        {
            "id_card": "110101199001011234",
            "patient_name": "张三",
            "department": "神经内科",
            "doctor_name": "朱以诚",
            "appointment_date": date1,
            "time_of_day": "上午",
            "appointment_time": f"{date1}-上午",
            "status": "BOOKED",
            "note": "doctor=朱以诚",
        },
        {
            "id_card": "110101199202021111",
            "patient_name": "李四",
            "department": "口腔科",
            "doctor_name": "万阔",
            "appointment_date": date1,
            "time_of_day": "下午",
            "appointment_time": f"{date1}-下午",
            "status": "BOOKED",
            "note": "doctor=万阔",
        },
        {
            "id_card": "110101198812123333",
            "patient_name": "王五",
            "department": "心内科",
            "doctor_name": "心内科门诊A",
            "appointment_date": date2,
            "time_of_day": "上午",
            "appointment_time": f"{date2}-上午",
            "status": "BOOKED",
            "note": "doctor=心内科门诊A",
        },
        {
            "id_card": "110101199611221999",
            "patient_name": "赵六",
            "department": "呼吸与危重症医学科",
            "doctor_name": "呼吸内科门诊A",
            "appointment_date": date2,
            "time_of_day": "下午",
            "appointment_time": f"{date2}-下午",
            "status": "BOOKED",
            "note": "doctor=呼吸内科门诊A",
        },
        {
            "id_card": "110101199903031888",
            "patient_name": "孙七",
            "department": "消化内科",
            "doctor_name": "消化内科门诊A",
            "appointment_date": date3,
            "time_of_day": "上午",
            "appointment_time": f"{date3}-上午",
            "status": "BOOKED",
            "note": "doctor=消化内科门诊A",
        },
    ]

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
