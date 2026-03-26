from __future__ import annotations

from datetime import datetime

from langchain_core.tools import tool

from app.db import Appointment, DoctorSchedule, SessionLocal, User


def _parse_time_of_day(value: str) -> str:
    text = value.strip()
    if text in ("上午", "am", "AM", "morning"):
        return "上午"
    if text in ("下午", "pm", "PM", "afternoon"):
        return "下午"
    return text


def _validate_date(date_text: str) -> bool:
    try:
        datetime.strptime(date_text, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _get_or_create_user(session, patient_name: str, id_card: str) -> User:
    user = session.query(User).filter(User.id_card == id_card).first()
    if user:
        if user.name != patient_name:
            user.name = patient_name
        return user
    user = User(name=patient_name, id_card=id_card)
    session.add(user)
    session.flush()
    return user


def _find_schedule(session, department: str, appointment_date: str, time_of_day: str, doctor: str):
    query = (
        session.query(DoctorSchedule)
        .filter(DoctorSchedule.department == department)
        .filter(DoctorSchedule.schedule_date == appointment_date)
        .filter(DoctorSchedule.time_of_day == time_of_day)
        .filter(DoctorSchedule.status == "ACTIVE")
    )
    if doctor:
        query = query.filter(DoctorSchedule.doctor_name == doctor)
    return query.order_by(DoctorSchedule.available_slots.desc(), DoctorSchedule.id.asc()).first()


@tool
def recommend_department(symptom: str) -> str:
    """根据症状推荐科室。入参 symptom 为用户主诉或症状描述。"""
    text = symptom.lower()
    mapping = [
        (("头痛", "头晕", "癫痫", "失眠", "神经"), "神经内科"),
        (("牙", "口腔", "牙龈", "龋齿", "牙痛"), "口腔科"),
        (("胸闷", "心悸", "心前区", "心脏"), "心内科"),
        (("咳嗽", "发热", "呼吸", "肺"), "呼吸与危重症医学科"),
        (("胃", "腹痛", "消化", "腹泻"), "消化内科"),
    ]
    for keywords, department in mapping:
        if any(keyword in text for keyword in keywords):
            return f"建议优先挂号：{department}。如症状加重请及时线下就医。"
    return "可先考虑全科医学科（普通内科）初诊，再由医生进行分诊。"


@tool
def check_registration_slots(department: str, appointment_date: str) -> str:
    """查询指定科室在某日的号源余量。入参：department, appointment_date(YYYY-MM-DD)。"""
    if not _validate_date(appointment_date):
        return "日期格式错误，请使用 YYYY-MM-DD。"

    with SessionLocal() as session:
        schedules = (
            session.query(DoctorSchedule)
            .filter(DoctorSchedule.department == department)
            .filter(DoctorSchedule.schedule_date == appointment_date)
            .order_by(DoctorSchedule.time_of_day.asc(), DoctorSchedule.doctor_name.asc())
            .all()
        )

    if not schedules:
        return f"未查询到 {department} 在 {appointment_date} 的排班信息。"

    lines = [f"{department} 在 {appointment_date} 的排班号源："]
    for schedule in schedules:
        lines.append(
            f"医生={schedule.doctor_name}, 时段={schedule.time_of_day}, 状态={schedule.status}, 剩余={schedule.available_slots}/{schedule.total_slots}"
        )
    return "\n".join(lines)


@tool
def book_appointment(
    patient_name: str,
    id_card: str,
    department: str,
    appointment_date: str,
    time_of_day: str,
    doctor: str = "",
) -> str:
    """预约挂号。必填：patient_name,id_card,department,appointment_date(YYYY-MM-DD),time_of_day(上午/下午)；doctor可选。"""
    if not all([patient_name, id_card, department, appointment_date, time_of_day]):
        return "预约失败：请补全姓名、身份证号、科室、日期、时段。"
    if not _validate_date(appointment_date):
        return "预约失败：日期格式错误，请使用 YYYY-MM-DD。"

    normalized_time = _parse_time_of_day(time_of_day)
    if normalized_time not in ("上午", "下午"):
        return "预约失败：time_of_day 仅支持 上午 或 下午。"

    with SessionLocal() as session:
        user = _get_or_create_user(session, patient_name, id_card)
        schedule = _find_schedule(session, department, appointment_date, normalized_time, doctor)
        if not schedule:
            return f"预约失败：未找到 {department} 在 {appointment_date} {normalized_time} 的可用排班。"
        if schedule.available_slots <= 0:
            return f"预约失败：{schedule.doctor_name} 在 {appointment_date} {normalized_time} 号源已满。"

        schedule.available_slots -= 1
        selected_doctor = doctor or schedule.doctor_name
        row = Appointment(
            user_id=user.id,
            patient_name=patient_name,
            id_card=id_card,
            department=department,
            doctor_name=selected_doctor,
            appointment_date=appointment_date,
            time_of_day=normalized_time,
            appointment_time=f"{appointment_date}-{normalized_time}",
            status="BOOKED",
            note=f"doctor={selected_doctor}",
        )
        session.add(row)
        session.commit()
        session.refresh(row)

    return (
        f"预约成功，订单号 {row.id}。"
        f"患者：{patient_name}，科室：{department}，时间：{appointment_date}-{normalized_time}，医生：{selected_doctor}。"
    )


@tool
def cancel_appointment(
    patient_name: str,
    id_card: str,
    department: str,
    appointment_date: str,
    time_of_day: str,
    doctor: str = "",
) -> str:
    """取消预约。必填：patient_name,id_card,department,appointment_date(YYYY-MM-DD),time_of_day(上午/下午)；doctor可选用于精确匹配。"""
    if not all([patient_name, id_card, department, appointment_date, time_of_day]):
        return "取消失败：请补全姓名、身份证号、科室、日期、时段。"
    if not _validate_date(appointment_date):
        return "取消失败：日期格式错误，请使用 YYYY-MM-DD。"

    normalized_time = _parse_time_of_day(time_of_day)

    with SessionLocal() as session:
        user = session.query(User).filter(User.id_card == id_card).first()
        if not user or user.name != patient_name:
            return "取消失败：未找到匹配的用户信息，请核对姓名和身份证号。"

        rows = (
            session.query(Appointment)
            .filter(Appointment.user_id == user.id)
            .filter(Appointment.patient_name == patient_name)
            .filter(Appointment.id_card == id_card)
            .filter(Appointment.department == department)
            .filter(Appointment.appointment_date == appointment_date)
            .filter(Appointment.time_of_day == normalized_time)
            .filter(Appointment.status == "BOOKED")
            .order_by(Appointment.id.desc())
            .all()
        )

        matched = None
        for row in rows:
            if doctor and row.doctor_name != doctor:
                continue
            matched = row
            break

        if not matched:
            return "取消失败：未找到匹配的预约记录，请核对信息。"

        schedule = _find_schedule(
            session,
            matched.department,
            matched.appointment_date,
            matched.time_of_day,
            matched.doctor_name,
        )
        if schedule:
            schedule.available_slots = min(schedule.available_slots + 1, schedule.total_slots)

        appointment_id = matched.id
        matched.status = "CANCELLED"
        session.commit()

    return f"取消成功，已取消订单号 {appointment_id}。"


@tool
def query_appointment_records(patient_name: str, id_card: str) -> str:
    """查询某位患者的预约记录。入参：patient_name,id_card。"""
    if not patient_name or not id_card:
        return "查询失败：请提供姓名和身份证号。"

    with SessionLocal() as session:
        user = session.query(User).filter(User.id_card == id_card).first()
        if not user or user.name != patient_name:
            return "暂无匹配的预约记录。"

        rows = session.query(Appointment).filter(Appointment.user_id == user.id).order_by(Appointment.id.desc()).all()

    if not rows:
        return "暂无匹配的预约记录。"

    lines = []
    for row in rows[:10]:
        lines.append(
            f"订单号={row.id}, 科室={row.department}, 医生={row.doctor_name}, 时间={row.appointment_time}, 状态={row.status}"
        )
    return "\n".join(lines)


def get_agent_tools():
    return [
        recommend_department,
        check_registration_slots,
        book_appointment,
        cancel_appointment,
        query_appointment_records,
    ]
