from __future__ import annotations

import json
import re
from datetime import datetime
from importlib import import_module
from pathlib import Path
from typing import Any

from app.core.config import settings


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
        return "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in str(memory_id))

    def _log_path(self, memory_id: str) -> Path:
        return settings.logs_dir / f"conversation_{self._safe_memory_id(memory_id)}.jsonl"

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
        record = {
            "timestamp": timestamp,
            "memory_id": memory_id,
            "question": question,
            "answer": answer,
            "memory_context": memory_context,
            "retrieved_context": retrieved_context,
            "tool_trace": tool_trace or [],
        }
        with self._log_path(memory_id).open("a", encoding="utf-8") as file_obj:
            file_obj.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._upsert_mongo_turn(memory_id, question, answer, timestamp)

    def list_sessions(self, user_id: int) -> list[dict[str, Any]]:
        if self._collection is None:
            return []
        rows = self._collection.find({"user_id": user_id}, {"_id": 0, "messages": 0}).sort("updated_at", -1)
        return list(rows)

    def get_session_detail(self, user_id: int, memory_id: str) -> dict[str, Any] | None:
        if self._collection is None:
            return None
        safe_id = self._safe_memory_id(memory_id)
        return self._collection.find_one({"user_id": user_id, "memory_id": safe_id}, {"_id": 0})
