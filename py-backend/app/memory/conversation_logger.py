from __future__ import annotations

import json
import re
from datetime import datetime
from importlib import import_module
from pathlib import Path
from typing import Any

from app.core.config import settings


def _safe_memory_id(memory_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in str(memory_id))


def _log_path(memory_id: str) -> Path:
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    return settings.logs_dir / f"conversation_{_safe_memory_id(memory_id)}.jsonl"


def _append_event(
    memory_id: str,
    event_type: str,
    name: str,
    request_payload: Any,
    response_payload: Any,
    metadata: dict[str, Any] | None = None,
) -> None:
    safe_request = request_payload if request_payload not in (None, "") else {"empty": True}
    safe_response = response_payload if response_payload not in (None, "") else {"empty": True}
    record = {
        "event_type": event_type,
        "timestamp": datetime.utcnow().isoformat(),
        "memory_id": memory_id,
        "name": name,
        "metadata": metadata or {},
    }
    if event_type == "llm_call":
        record["llm_request"] = safe_request
        record["llm_response"] = safe_response
    elif event_type == "chat_turn":
        record["user_request"] = safe_request
        record["assistant_response"] = safe_response
    else:
        record["request"] = safe_request
        record["response"] = safe_response
    with _log_path(memory_id).open("a", encoding="utf-8") as file_obj:
        file_obj.write(json.dumps(record, ensure_ascii=False) + "\n")


def log_llm_call(
    memory_id: str,
    call_name: str,
    request_payload: Any,
    response_payload: Any,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Append a single LLM-call event to the per-session JSONL log.

    This is intentionally file-only logging so it can be used from any module
    (graph / intent routing / memory compression) without coupling to Mongo upsert logic.
    """
    try:
        _append_event(
            memory_id=memory_id,
            event_type="llm_call",
            name=call_name,
            request_payload=request_payload,
            response_payload=response_payload,
            metadata=metadata,
        )
    except Exception:
        pass


class ConversationLogger:
    def __init__(self):
        settings.logs_dir.mkdir(parents=True, exist_ok=True)
        self._collection = None
        try:
            mongo_module = import_module("pymongo")
            mongo_client_cls = getattr(mongo_module, "MongoClient")
            client = mongo_client_cls(settings.mongo_uri, serverSelectionTimeoutMS=settings.mongo_timeout_ms)
            client.admin.command("ping")
            self._collection = client[settings.mongo_db][settings.mongo_conversation_collection]
            self._collection.create_index([("user_id", 1), ("updated_at", -1)])
            self._collection.create_index("memory_id", unique=True)
        except Exception:
            self._collection = None

    def _safe_memory_id(self, memory_id: str) -> str:
        return _safe_memory_id(memory_id)

    def _log_path(self, memory_id: str) -> Path:
        return _log_path(memory_id)

    def _parse_scoped_memory(self, memory_id: str) -> tuple[int | None, str]:
        match = re.match(r"^user_(\d+)_mem_(.+)$", memory_id)
        if not match:
            return None, memory_id
        return int(match.group(1)), match.group(2)

    def _upsert_mongo_turn(self, memory_id: str, question: str, answer: str, timestamp: str) -> None:
        if self._collection is None:
            return

        user_id, memory_suffix = self._parse_scoped_memory(memory_id)
        safe_id = self._safe_memory_id(memory_id)
        update_doc = {
            "$set": {
                "memory_id": safe_id,
                "memory_suffix": memory_suffix,
                "updated_at": timestamp,
                "last_question": question,
                "last_answer": answer,
            },
            "$inc": {"turns": 1},
            "$push": {
                "messages": {
                    "$each": [
                        {"role": "user", "content": question, "ts": timestamp},
                        {"role": "assistant", "content": answer, "ts": timestamp},
                    ]
                }
            },
            "$setOnInsert": {
                "created_at": timestamp,
                "title": (question or "新会话")[:40],
            },
        }
        if user_id is not None:
            update_doc["$set"]["user_id"] = user_id

        self._collection.update_one({"memory_id": safe_id}, update_doc, upsert=True)

    def log_turn(
        self,
        memory_id: str,
        question: str,
        answer: str,
        memory_context: str,
        retrieved_context: str,
        tool_trace: list[dict[str, Any]] | None = None,
    ) -> None:
        timestamp = datetime.utcnow().isoformat()
        try:
            _append_event(
                memory_id=memory_id,
                event_type="chat_turn",
                name="chat.turn",
                request_payload={
                    "question": question,
                    "memory_context": memory_context,
                    "retrieved_context": retrieved_context,
                },
                response_payload={
                    "answer": answer,
                    "tool_trace": tool_trace or [],
                },
            )
        except Exception:
            pass
        self._upsert_mongo_turn(memory_id, question, answer, timestamp)

    def list_sessions(self, user_id: int) -> list[dict[str, Any]]:
        if self._collection is None:
            return []
        rows = self._collection.find({"user_id": user_id}, {"_id": 0, "messages": 0}).sort("updated_at", -1)
        result: list[dict[str, Any]] = []
        for row in rows:
            scoped_id = str(row.get("memory_id", "") or "")
            suffix = str(row.get("memory_suffix", "") or "")
            if not suffix and scoped_id:
                _, parsed_suffix = self._parse_scoped_memory(scoped_id)
                suffix = parsed_suffix
            result.append(
                {
                    "memoryId": suffix or scoped_id,
                    "scopedMemoryId": scoped_id,
                    "title": row.get("title", ""),
                    "turns": row.get("turns", 0),
                    "updatedAt": row.get("updated_at", ""),
                }
            )
        return result

    def get_session_detail(self, user_id: int, memory_id: str) -> dict[str, Any] | None:
        if self._collection is None:
            return None
        candidates = [self._safe_memory_id(memory_id)]
        raw = str(memory_id)
        if not raw.startswith("user_"):
            candidates.append(self._safe_memory_id(f"user_{user_id}_mem_{raw}"))

        for safe_id in candidates:
            data = self._collection.find_one({"user_id": user_id, "memory_id": safe_id}, {"_id": 0})
            if data:
                return data
        return None
