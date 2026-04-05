from __future__ import annotations

import re
from typing import Any

from langchain_core.messages import HumanMessage

from app.memory.conversation_logger import log_llm_call
from app.utils.prompt_loader import render_prompt

WORKFLOW_INTENT_LABELS = {
    "recommend_department": "分导诊",
    "check_registration_slots": "查号源",
    "book_appointment": "预约挂号",
    "cancel_appointment": "取消挂号",
    "query_appointment_records": "查询预约记录",
}

INTENT_KEYWORDS = {
    "recommend_department": ("挂什么科", "什么科", "分诊", "导诊"),
    "check_registration_slots": ("查号源", "号源", "有号", "余号"),
    "book_appointment": ("预约", "挂号", "约号", "帮我挂"),
    "cancel_appointment": ("取消", "退号"),
    "query_appointment_records": ("预约记录", "记录查询", "我的预约"),
}

INTENT_REQUIRED_FIELDS = {
    "recommend_department": ["symptom"],
    "check_registration_slots": ["department", "appointment_date"],
    "book_appointment": ["patient_name", "id_card", "department", "appointment_date", "time_of_day"],
    "cancel_appointment": ["patient_name", "id_card", "department", "appointment_date", "time_of_day"],
    "query_appointment_records": ["patient_name", "id_card"],
}

FIELD_LABELS = {
    "symptom": "症状描述",
    "patient_name": "姓名",
    "id_card": "身份证号",
    "department": "预约科室",
    "appointment_date": "预约日期（YYYY-MM-DD）",
    "time_of_day": "预约时间（上午/下午）",
}

ASSISTANT_INTENT_HINTS = {
    "recommend_department": ("分导诊", "挂什么科", "什么科", "分诊", "导诊", "症状"),
    "check_registration_slots": ("查号源", "号源", "排班", "可预约", "余号"),
    "book_appointment": ("预约", "挂号", "办理挂号", "提交挂号", "预约信息", "就诊时间"),
    "cancel_appointment": ("取消", "退号", "取消预约", "取消挂号"),
    "query_appointment_records": ("预约记录", "历史预约", "记录查询", "我的预约"),
}

INTENT_ORDER = (
    "recommend_department",
    "check_registration_slots",
    "book_appointment",
    "cancel_appointment",
    "query_appointment_records",
)

ROUTER_ALLOWED_INTENTS = set(INTENT_ORDER) | {"none"}
SMALL_TALK_PHRASES = {
    "你好",
    "您好",
    "在吗",
    "谢谢",
    "感谢",
    "好的",
    "嗯",
    "嗯嗯",
    "明白了",
    "知道了",
    "再见",
    "拜拜",
}


def detect_intent_candidates(question: str) -> list[str]:
    text = (question or "").strip()
    if not text:
        return []
    matched: list[str] = []
    for intent, keywords in INTENT_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            matched.append(intent)
    return matched


def looks_like_slot_answer(text: str) -> bool:
    if re.search(r"\b\d{17}[\dXx]\b", text):
        return True
    if re.search(r"\b\d{4}-\d{1,2}-\d{1,2}\b", text):
        return True
    if any(token in text for token in ("上午", "下午", "am", "pm", "AM", "PM")):
        return True
    if "科" in text and len(text) <= 16:
        return True
    if re.search(r"(我叫|我是|姓名是)[\u4e00-\u9fa5]{2,8}", text):
        return True
    return False


def extract_fields_from_text(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    question = (text or "").strip()
    if not question:
        return result

    id_card_match = re.search(r"\b\d{17}[\dXx]\b", question)
    if id_card_match:
        result["id_card"] = id_card_match.group(0)

    date_match = re.search(r"\b\d{4}-\d{1,2}-\d{1,2}\b", question)
    if date_match:
        result["appointment_date"] = date_match.group(0)

    if any(token in question for token in ("上午", "am", "AM")):
        result["time_of_day"] = "上午"
    elif any(token in question for token in ("下午", "pm", "PM")):
        result["time_of_day"] = "下午"

    name_match = re.search(r"(?:我叫|我是|姓名是)([\u4e00-\u9fa5]{2,8})", question)
    if name_match:
        result["patient_name"] = name_match.group(1)

    department_match = re.search(r"([\u4e00-\u9fa5]{2,20}(?:科|门诊|医学科))", question)
    if department_match:
        result["department"] = department_match.group(1)

    return result


def _get_recent_working_memory_messages(memory_store: Any, memory_id: str) -> list[dict[str, str]]:
    data = memory_store.load(memory_id)
    messages = data.get("working_memory", []) if isinstance(data, dict) else []
    if not isinstance(messages, list):
        return []
    normalized: list[dict[str, str]] = []
    for item in messages[-6:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "") or "")
        content = str(item.get("content", "") or "")
        if role and content:
            normalized.append({"role": role, "content": content})
    return normalized


def _assistant_hint_to_intent(text: str) -> str:
    for intent in INTENT_ORDER:
        hints = ASSISTANT_INTENT_HINTS.get(intent, ())
        if any(hint in text for hint in hints):
            return intent
    return ""


def _merge_collected_fields(required_fields: list[str], previous_collected: dict[str, str], text: str) -> dict[str, str]:
    collected = dict(previous_collected)
    extracted = extract_fields_from_text(text)
    for key in required_fields:
        value = str(extracted.get(key, "") or "").strip()
        if value:
            collected[key] = value

    if "symptom" in required_fields and not collected.get("symptom"):
        plain_text = text.replace("挂什么科", "").replace("分诊", "").strip()
        if plain_text:
            collected["symptom"] = plain_text

    return collected


def _persist_tool_state(
    memory_store: Any,
    memory_id: str,
    intent: str,
    required_fields: list[str],
    collected_fields: dict[str, str],
) -> dict[str, Any]:
    data = memory_store.load(memory_id)
    if not isinstance(data, dict):
        data = {}
    missing_fields = [field for field in required_fields if not collected_fields.get(field)]
    status = "idle"
    if intent:
        status = "collecting_slots" if missing_fields else "ready"
    data["tool_working_memory"] = {
        "intent": intent,
        "required_fields": required_fields,
        "collected_fields": collected_fields,
        "missing_fields": missing_fields,
        "status": status,
        "last_tool_calls": list(data.get("tool_working_memory", {}).get("last_tool_calls", []))
        if isinstance(data.get("tool_working_memory", {}), dict)
        else [],
        "updated_at": data.get("tool_working_memory", {}).get("updated_at") if isinstance(data.get("tool_working_memory", {}), dict) else None,
    }
    memory_store.save(memory_id, data)
    return data


def _looks_like_followup_answer(question: str) -> bool:
    text = (question or "").strip()
    if not text:
        return False
    if text in SMALL_TALK_PHRASES:
        return False
    if re.fullmatch(r"[\u4e00-\u9fa5]{2,12}(?:医生|吧)?", text):
        return True
    if re.search(r"\b\d{17}[\dXx]\b", text):
        return True
    if re.search(r"\b\d{4}-\d{1,2}-\d{1,2}\b", text):
        return True
    if any(token in text for token in ("上午", "下午", "am", "pm", "AM", "PM")):
        return True
    if re.search(r"(我叫|我是|姓名是)[\u4e00-\u9fa5]{2,8}", text):
        return True
    return False


def _classify_intent_with_llm(memory_store: Any, memory_id: str, question: str, previous_intent: str, previous_status: str) -> str:
    llm = getattr(memory_store, "llm", None)
    if llm is None:
        return ""

    recent_messages = _get_recent_working_memory_messages(memory_store, memory_id)
    recent_context = "\n".join(f"{item['role']}: {item['content']}" for item in recent_messages[-4:])
    prompt = render_prompt(
        "intent_router_prompt.txt",
        question=question,
        previous_intent=previous_intent or "none",
        previous_status=previous_status or "idle",
        recent_context=recent_context or "暂无",
    )
    try:
        res = llm.invoke([HumanMessage(content=prompt)])
        text = res.content if isinstance(res.content, str) else str(res.content)
        log_llm_call(
            memory_id=memory_id,
            call_name="chat.intent_router.invoke",
            request_payload={"prompt": prompt},
            response_payload={"content": text},
            metadata={"previous_intent": previous_intent, "previous_status": previous_status},
        )
    except Exception:
        return ""

    parsed = _extract_json_from_text(text)
    intent = str(parsed.get("intent", "") or "").strip()
    if intent in ROUTER_ALLOWED_INTENTS:
        return intent
    return ""


def _is_non_workflow_chat(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return True
    if normalized in SMALL_TALK_PHRASES:
        return True
    if re.fullmatch(r"[\u4e00-\u9fa5]{1,6}[~！!。.?？]?", normalized) and normalized.replace("！", "").replace("!", "").replace("。", "").replace("?", "").replace("？", "") in SMALL_TALK_PHRASES:
        return True
    return False


def _extract_json_from_text(text: str) -> dict[str, Any]:
    left = text.find("{")
    right = text.rfind("}")
    if left == -1 or right == -1 or right <= left:
        return {}
    try:
        import json as _json

        data = _json.loads(text[left : right + 1])
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def format_missing_fields_question(intent: str, missing_fields: list[str]) -> str:
    labels = [FIELD_LABELS.get(field, field) for field in missing_fields]
    missing_text = "、".join(labels)
    intent_label = WORKFLOW_INTENT_LABELS.get(intent, "当前就医流程")
    return (
        f"为帮您继续{intent_label}，还需要补充：{missing_text}。\n"
        "可直接按这个格式回复：姓名 + 身份证号 + 科室 + 日期(YYYY-MM-DD) + 上午/下午。"
    )


def build_clarification_if_needed(memory_store: Any, memory_id: str, question: str) -> str | None:
    text = (question or "").strip()
    if not text:
        return "我还不清楚您的需求，请问您是要分导诊、查号源、预约挂号、取消挂号，还是查询预约记录？"

    current_data = memory_store.load(memory_id)
    tool_state = current_data.get("tool_working_memory", {}) if isinstance(current_data, dict) else {}
    previous_intent = str(tool_state.get("intent", "") or "")
    previous_status = str(tool_state.get("status", "") or "")
    previous_collected = tool_state.get("collected_fields", {}) if isinstance(tool_state.get("collected_fields", {}), dict) else {}

    if _is_non_workflow_chat(text):
        # Small talk should not interrupt an in-progress workflow.
        if previous_intent and previous_status in ("collecting_slots", "ready", "tool_called"):
            return None
        _persist_tool_state(memory_store, memory_id, "", [], {})
        return None

    candidates = detect_intent_candidates(text)
    intent = ""

    if len(candidates) > 1 and not previous_intent:
        return "为避免误操作，请确认您这次是要：1) 分导诊 2) 查号源 3) 预约挂号 4) 取消挂号 5) 查询预约记录。"

    if previous_intent and previous_status in ("collecting_slots", "ready", "tool_called"):
        if not candidates or previous_intent in candidates or looks_like_slot_answer(text):
            intent = previous_intent

    if not intent and len(candidates) == 1:
        intent = candidates[0]

    if not intent:
        assistant_hint = ""
        for item in reversed(_get_recent_working_memory_messages(memory_store, memory_id)):
            if item["role"] != "assistant":
                continue
            assistant_hint = item["content"]
            break
        if assistant_hint and _looks_like_followup_answer(text):
            inferred = _assistant_hint_to_intent(assistant_hint)
            if inferred:
                intent = inferred

    if not intent:
        intent = _classify_intent_with_llm(memory_store, memory_id, text, previous_intent, previous_status)

    if intent == "none":
        _persist_tool_state(memory_store, memory_id, "", [], {})
        return None

    if not intent:
        return None

    required_fields = INTENT_REQUIRED_FIELDS.get(intent, [])
    if not required_fields:
        return None

    collected = _merge_collected_fields(required_fields, dict(previous_collected) if previous_intent == intent else {}, text)
    missing_fields = [field for field in required_fields if not collected.get(field)]
    _persist_tool_state(memory_store, memory_id, intent, required_fields, collected)
    if missing_fields:
        return format_missing_fields_question(intent, missing_fields)

    return None
