from __future__ import annotations

import json
import re
from datetime import datetime
from importlib import import_module
from typing import Any

import jieba
from langchain_core.messages import HumanMessage
from rank_bm25 import BM25Okapi

from app.config import settings
from app.prompt_loader import render_prompt


class LayeredMemoryStore:
    def __init__(self, llm):
        self.llm = llm
        try:
            mongo_module = import_module("pymongo")
            mongo_client_cls = getattr(mongo_module, "MongoClient")
        except ModuleNotFoundError as exc:
            raise RuntimeError("pymongo is required, please run: pip install -r requirements.txt") from exc

        self._client = mongo_client_cls(settings.mongo_uri, serverSelectionTimeoutMS=settings.mongo_timeout_ms)
        self._session_collection: Any = self._client[settings.mongo_db][settings.mongo_memory_collection]
        self._profile_collection: Any = self._client[settings.mongo_db][settings.mongo_user_profile_collection]
        # 启动时尽早校验连接，避免运行中才发现不可用
        self._client.admin.command("ping")
        self._session_collection.create_index("memory_id", unique=True)
        self._session_collection.create_index("user_id")
        self._profile_collection.create_index("user_id", unique=True)

    def _safe_memory_id(self, memory_id: str) -> str:
        return "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in str(memory_id))

    def _default(self) -> dict:
        return {
            "working_memory": [],
            "short_term_summary": "",
            "session_facts": [],
            "tool_working_memory": self._default_tool_working_memory(),
            "last_compressed_at": None,
        }

    def _default_tool_working_memory(self) -> dict:
        return {
            "intent": "",
            "required_fields": [],
            "collected_fields": {},
            "missing_fields": [],
            "status": "idle",
            "last_tool_calls": [],
            "updated_at": None,
        }

    def _default_profile(self) -> dict:
        return {
            "identity": {
                "patient_name": "",
                "id_card": "",
            },
            "medical_history": [],
            "allergies": [],
            "medications": [],
            "preferences": [],
            "care_plan": [],
            "long_term_memory_items": [],
        }

    def _parse_scoped_memory(self, memory_id: str) -> tuple[int | None, str]:
        match = re.match(r"^user_(\d+)_mem_(.+)$", memory_id)
        if not match:
            return None, memory_id
        return int(match.group(1)), match.group(2)

    def _normalize_doc(self, doc: dict | None) -> dict:
        base = self._default()
        if not doc:
            return base
        base["working_memory"] = list(doc.get("working_memory", []))
        base["short_term_summary"] = str(doc.get("short_term_summary", "") or "")
        # 兼容旧字段 long_term_facts，迁移到会话稳定事实 session_facts
        facts = doc.get("session_facts")
        if facts is None:
            facts = doc.get("long_term_facts", [])
        base["session_facts"] = [str(x).strip() for x in list(facts or []) if str(x).strip()]
        base["tool_working_memory"] = self._normalize_tool_working_memory(doc.get("tool_working_memory"))
        base["last_compressed_at"] = doc.get("last_compressed_at")
        return base

    def _normalize_tool_working_memory(self, data: dict | None) -> dict:
        base = self._default_tool_working_memory()
        if not isinstance(data, dict):
            return base
        base["intent"] = str(data.get("intent", "") or "")
        base["required_fields"] = [str(x) for x in list(data.get("required_fields", []) or []) if str(x)]
        collected = data.get("collected_fields", {}) if isinstance(data.get("collected_fields", {}), dict) else {}
        base["collected_fields"] = {str(k): str(v) for k, v in collected.items() if str(v).strip()}
        base["missing_fields"] = [str(x) for x in list(data.get("missing_fields", []) or []) if str(x)]
        base["status"] = str(data.get("status", "idle") or "idle")
        calls = list(data.get("last_tool_calls", []) or [])
        normalized_calls: list[dict[str, Any]] = []
        for item in calls[-4:]:
            if not isinstance(item, dict):
                continue
            normalized_calls.append(
                {
                    "tool": str(item.get("tool", "") or ""),
                    "args": item.get("args", {}) if isinstance(item.get("args", {}), dict) else {},
                    "result": str(item.get("result", "") or "")[:200],
                    "ts": item.get("ts"),
                }
            )
        base["last_tool_calls"] = normalized_calls
        base["updated_at"] = data.get("updated_at")
        return base

    def _normalize_profile(self, doc: dict | None) -> dict:
        base = self._default_profile()
        if not doc:
            return base
        profile = doc.get("profile", {}) if isinstance(doc.get("profile", {}), dict) else {}
        identity = profile.get("identity", {}) if isinstance(profile.get("identity", {}), dict) else {}
        base["identity"] = {
            "patient_name": str(identity.get("patient_name", "") or "").strip(),
            "id_card": str(identity.get("id_card", "") or "").strip(),
        }
        for key in ("medical_history", "allergies", "medications", "preferences", "care_plan"):
            base[key] = [str(x).strip() for x in list(profile.get(key, []) or []) if str(x).strip()]
        items = list(profile.get("long_term_memory_items", []) or [])
        normalized_items: list[dict[str, str]] = []
        for item in items[:200]:
            if isinstance(item, str):
                text = item.strip()
                if text:
                    normalized_items.append({"text": text, "ts": ""})
                continue
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", "") or "").strip()
            if not text:
                continue
            normalized_items.append({"text": text, "ts": str(item.get("ts", "") or "")})
        base["long_term_memory_items"] = normalized_items
        return base

    def _infer_intent(self, question: str, tool_trace: list[dict[str, Any]]) -> str:
        tool_names = [str(t.get("tool", "") or "") for t in tool_trace]
        if "book_appointment" in tool_names:
            return "book_appointment"
        if "cancel_appointment" in tool_names:
            return "cancel_appointment"
        if "check_registration_slots" in tool_names:
            return "check_registration_slots"
        if "query_appointment_records" in tool_names:
            return "query_appointment_records"
        if "recommend_department" in tool_names:
            return "recommend_department"

        q = question.strip()
        if any(k in q for k in ("挂号", "预约", "约号")):
            return "book_appointment"
        if any(k in q for k in ("取消", "退号")):
            return "cancel_appointment"
        if any(k in q for k in ("号源", "有号", "余号")):
            return "check_registration_slots"
        if any(k in q for k in ("预约记录", "记录查询", "我的预约")):
            return "query_appointment_records"
        if any(k in q for k in ("挂什么科", "什么科", "分诊", "导诊")):
            return "recommend_department"
        return ""

    def _required_fields_for_intent(self, intent: str) -> list[str]:
        mapping = {
            "book_appointment": ["patient_name", "id_card", "department", "appointment_date", "time_of_day"],
            "cancel_appointment": ["patient_name", "id_card", "department", "appointment_date", "time_of_day"],
            "check_registration_slots": ["department", "appointment_date"],
            "query_appointment_records": ["patient_name", "id_card"],
            "recommend_department": ["symptom"],
        }
        return mapping.get(intent, [])

    def _build_tool_working_memory(
        self,
        question: str,
        tool_trace: list[dict[str, Any]],
        previous: dict | None,
    ) -> dict:
        prev = self._normalize_tool_working_memory(previous)
        intent = self._infer_intent(question, tool_trace) or prev.get("intent", "")
        required_fields = self._required_fields_for_intent(intent)
        collected: dict[str, str] = dict(prev.get("collected_fields", {}))

        for call in tool_trace:
            args = call.get("args", {}) if isinstance(call.get("args", {}), dict) else {}
            for key in required_fields:
                value = str(args.get(key, "") or "").strip()
                if value:
                    collected[key] = value

        missing_fields = [f for f in required_fields if not collected.get(f)]
        status = "idle"
        if intent:
            if tool_trace and not missing_fields:
                status = "tool_called"
            elif missing_fields:
                status = "collecting_slots"
            else:
                status = "ready"

        now = datetime.utcnow().isoformat()
        recent_calls = list(prev.get("last_tool_calls", []))
        for call in tool_trace:
            recent_calls.append(
                {
                    "tool": str(call.get("tool", "") or ""),
                    "args": call.get("args", {}) if isinstance(call.get("args", {}), dict) else {},
                    "result": str(call.get("result", "") or "")[:200],
                    "ts": now,
                }
            )

        return {
            "intent": intent,
            "required_fields": required_fields,
            "collected_fields": collected,
            "missing_fields": missing_fields,
            "status": status,
            "last_tool_calls": recent_calls[-4:],
            "updated_at": now,
        }

    def _should_route_long_term(self, question: str) -> bool:
        q = (question or "").strip()
        if not q:
            return False
        memory_keywords = (
            "之前",
            "上次",
            "还记得",
            "历史",
            "长期",
            "继续",
            "复诊",
            "过敏",
            "慢病",
            "我的信息",
            "我的情况",
            "按之前",
        )
        return any(k in q for k in memory_keywords)

    def _retrieve_long_term_memory(self, memory_id: str, query: str) -> list[str]:
        profile = self.load_user_profile(memory_id)
        items = profile.get("long_term_memory_items", [])
        texts = [str(item.get("text", "") or "").strip() for item in items if isinstance(item, dict)]
        texts = [x for x in texts if x]
        if not texts:
            return []

        tokenized = [list(jieba.cut(t)) for t in texts]
        bm25 = BM25Okapi(tokenized)
        scores = bm25.get_scores(list(jieba.cut(query)))
        top_k = max(1, settings.long_term_memory_top_k)
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        picked = [texts[i] for i in ranked[:top_k] if scores[i] > 0]
        return picked

    def _upsert_long_term_memory_items(self, memory_id: str, items: list[str]) -> None:
        clean_items = [str(x).strip() for x in items if str(x).strip()]
        if not clean_items:
            return
        profile = self.load_user_profile(memory_id)
        existing = profile.get("long_term_memory_items", [])
        existing_texts = [str(x.get("text", "") or "").strip() for x in existing if isinstance(x, dict)]
        merged_texts = self._merge_unique(existing_texts, clean_items, limit=200)
        now = datetime.utcnow().isoformat()
        profile["long_term_memory_items"] = [{"text": text, "ts": now} for text in merged_texts]
        self.save_user_profile(memory_id, profile)

    def _merge_unique(self, old_items: list[str], new_items: list[str], limit: int = 30) -> list[str]:
        merged = old_items + new_items
        seen: set[str] = set()
        deduped: list[str] = []
        for item in merged:
            key = item.strip()
            if key and key not in seen:
                seen.add(key)
                deduped.append(key)
        return deduped[:limit]

    def _extract_json_object(self, text: str) -> dict:
        left = text.find("{")
        right = text.rfind("}")
        if left == -1 or right == -1 or right <= left:
            return {}
        try:
            data = json.loads(text[left : right + 1])
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def load(self, memory_id: str) -> dict:
        safe_id = self._safe_memory_id(memory_id)
        doc = self._session_collection.find_one({"memory_id": safe_id}, {"_id": 0})
        if doc:
            return self._normalize_doc(doc)
        return self._default()

    def load_user_profile(self, memory_id: str) -> dict:
        user_id, _ = self._parse_scoped_memory(memory_id)
        if user_id is None:
            return self._default_profile()
        doc = self._profile_collection.find_one({"user_id": user_id}, {"_id": 0})
        return self._normalize_profile(doc)

    def save(self, memory_id: str, data: dict) -> None:
        safe_id = self._safe_memory_id(memory_id)
        user_id, memory_suffix = self._parse_scoped_memory(memory_id)
        payload = self._normalize_doc(data)
        payload["memory_id"] = safe_id
        if user_id is not None:
            payload["user_id"] = user_id
            payload["memory_suffix"] = memory_suffix
        payload["updated_at"] = datetime.utcnow().isoformat()
        self._session_collection.update_one(
            {"memory_id": safe_id},
            {"$set": payload, "$setOnInsert": {"created_at": datetime.utcnow().isoformat()}},
            upsert=True,
        )

    def save_user_profile(self, memory_id: str, profile: dict) -> None:
        user_id, _ = self._parse_scoped_memory(memory_id)
        if user_id is None:
            return
        payload = {
            "user_id": user_id,
            "profile": self._normalize_profile({"profile": profile}),
            "updated_at": datetime.utcnow().isoformat(),
        }
        self._profile_collection.update_one(
            {"user_id": user_id},
            {"$set": payload, "$setOnInsert": {"created_at": datetime.utcnow().isoformat()}},
            upsert=True,
        )

    def _render_profile_text(self, profile: dict) -> str:
        identity = profile.get("identity", {}) if isinstance(profile.get("identity", {}), dict) else {}
        lines: list[str] = []
        patient_name = str(identity.get("patient_name", "") or "").strip()
        id_card = str(identity.get("id_card", "") or "").strip()
        if patient_name:
            lines.append(f"- 姓名: {patient_name}")
        if id_card:
            lines.append(f"- 身份证号: {id_card}")
        for key, label in (
            ("medical_history", "病史"),
            ("allergies", "过敏史"),
            ("medications", "长期用药"),
            ("preferences", "就医偏好"),
            ("care_plan", "就医计划"),
        ):
            values = [str(x).strip() for x in profile.get(key, []) if str(x).strip()]
            if not values:
                continue
            lines.append(f"- {label}: {'；'.join(values[:6])}")
        return "\n".join(lines) if lines else "- 暂无"

    def _extract_user_profile_delta(self, memory_id: str, history: str) -> dict:
        current_profile = self.load_user_profile(memory_id)
        prompt = render_prompt(
            "user_profile_extract_prompt.txt",
            history=history,
            current_profile=json.dumps(current_profile, ensure_ascii=False),
        )
        res = self.llm.invoke([HumanMessage(content=prompt)])
        text = res.content if isinstance(res.content, str) else str(res.content)
        return self._extract_json_object(text)

    def _merge_user_profile(self, memory_id: str, delta: dict) -> None:
        if not delta:
            return
        current = self.load_user_profile(memory_id)
        identity_delta = delta.get("identity") if isinstance(delta.get("identity"), dict) else {}
        merged = self._default_profile()
        merged["identity"] = {
            "patient_name": str(identity_delta.get("patient_name") or current["identity"].get("patient_name") or "").strip(),
            "id_card": str(identity_delta.get("id_card") or current["identity"].get("id_card") or "").strip(),
        }

        for key in ("medical_history", "allergies", "medications", "preferences", "care_plan"):
            delta_items = [str(x).strip() for x in list(delta.get(key, []) or []) if str(x).strip()]
            merged[key] = self._merge_unique(current.get(key, []), delta_items)

        self.save_user_profile(memory_id, merged)

    def add_turn(self, memory_id: str, user_msg: str, ai_msg: str, tool_trace: list[dict[str, Any]] | None = None) -> None:
        data = self.load(memory_id)
        now = datetime.utcnow().isoformat()
        data["working_memory"].append({"role": "user", "content": user_msg, "ts": now})
        data["working_memory"].append({"role": "assistant", "content": ai_msg, "ts": now})
        data["tool_working_memory"] = self._build_tool_working_memory(
            question=user_msg,
            tool_trace=tool_trace or [],
            previous=data.get("tool_working_memory", {}),
        )

        # 保留工作记忆窗口
        max_items = settings.working_memory_window * 2
        data["working_memory"] = data["working_memory"][-max_items:]

        self.save(memory_id, data)

    def render_context(self, memory_id: str, question: str | None = None) -> str:
        data = self.load(memory_id)
        user_profile = self.load_user_profile(memory_id)
        working_lines = [f"{m['role']}: {m['content']}" for m in data["working_memory"]]
        working_text = "\n".join(working_lines) if working_lines else "暂无"
        session_facts = "\n".join(f"- {x}" for x in data["session_facts"])
        profile_text = self._render_profile_text(user_profile)
        task_state = self._normalize_tool_working_memory(data.get("tool_working_memory"))
        task_text = "- 暂无"
        if task_state.get("intent"):
            task_text = (
                f"- intent: {task_state.get('intent', '')}\n"
                f"- status: {task_state.get('status', '')}\n"
                f"- missing_fields: {', '.join(task_state.get('missing_fields', [])) or '无'}\n"
                f"- collected_fields: {json.dumps(task_state.get('collected_fields', {}), ensure_ascii=False)}"
            )

        routed_long_term = []
        if self._should_route_long_term(question or ""):
            routed_long_term = self._retrieve_long_term_memory(memory_id, question or "")
        routed_text = "\n".join([f"- {x}" for x in routed_long_term]) if routed_long_term else "- 本轮未命中长期记忆路由或无相关结果"
        return (
            "[短期摘要]\n"
            f"{data['short_term_summary'] or '暂无'}\n\n"
            "[会话稳定事实]\n"
            f"{session_facts or '- 暂无'}\n\n"
            "[函数调用工作记忆]\n"
            f"{task_text}\n\n"
            "[长期记忆检索结果]\n"
            f"{routed_text}\n\n"
            "[用户结构化长期记忆]\n"
            f"{profile_text}\n\n"
            "[工作记忆]\n"
            f"{working_text}"
        )

    def is_first_session(self, memory_id: str) -> bool:
        data = self.load(memory_id)
        has_working = len(data.get("working_memory", [])) > 0
        has_summary = bool(data.get("short_term_summary", "").strip())
        has_facts = len(data.get("session_facts", [])) > 0
        return not (has_working or has_summary or has_facts)

    def maybe_auto_compress(self, memory_id: str) -> bool:
        data = self.load(memory_id)
        combined_text = "\n".join([m["content"] for m in data["working_memory"]])
        if len(combined_text) < settings.auto_compress_trigger_chars:
            return False
        self.compress(memory_id)
        return True

    def compress(self, memory_id: str) -> dict:
        data = self.load(memory_id)
        history = "\n".join([f"{m['role']}: {m['content']}" for m in data["working_memory"]])
        if not history.strip():
            return data

        prompt = render_prompt("memory_compress_prompt.txt", history=history)
        res = self.llm.invoke([HumanMessage(content=prompt)])
        text = res.content if isinstance(res.content, str) else str(res.content)

        summary = text.strip()
        facts: list[str] = []
        left = text.find("[")
        right = text.rfind("]")
        if left != -1 and right != -1 and right > left:
            json_part = text[left : right + 1]
            try:
                parsed = json.loads(json_part)
                if isinstance(parsed, list):
                    facts = [str(x) for x in parsed][:20]
                    summary = text[:left].strip()
            except json.JSONDecodeError:
                pass

        if summary:
            data["short_term_summary"] = summary[:800]
        if facts:
            data["session_facts"] = self._merge_unique(data["session_facts"], facts, limit=50)
            self._upsert_long_term_memory_items(memory_id, facts)

        # 同步更新用户级结构化长期记忆，跨会话复用
        try:
            delta = self._extract_user_profile_delta(memory_id, history)
            self._merge_user_profile(memory_id, delta)
            extracted_items: list[str] = []
            for key in ("medical_history", "allergies", "medications", "preferences", "care_plan"):
                extracted_items.extend([str(x).strip() for x in list(delta.get(key, []) or []) if str(x).strip()])
            identity = delta.get("identity") if isinstance(delta.get("identity"), dict) else {}
            if str(identity.get("patient_name", "") or "").strip():
                extracted_items.append(f"姓名: {str(identity.get('patient_name', '')).strip()}")
            if str(identity.get("id_card", "") or "").strip():
                extracted_items.append(f"身份证号: {str(identity.get('id_card', '')).strip()}")
            self._upsert_long_term_memory_items(memory_id, extracted_items)
        except Exception:
            # 画像抽取失败不影响主流程
            pass

        # 压缩后只保留最近两轮在工作记忆中
        data["working_memory"] = data["working_memory"][-4:]
        data["last_compressed_at"] = datetime.utcnow().isoformat()
        self.save(memory_id, data)
        return data
