from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import settings


class ConversationLogger:
    def __init__(self):
        settings.logs_dir.mkdir(parents=True, exist_ok=True)

    def _safe_memory_id(self, memory_id: str) -> str:
        return "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in str(memory_id))

    def _log_path(self, memory_id: str) -> Path:
        return settings.logs_dir / f"conversation_{self._safe_memory_id(memory_id)}.jsonl"

    def log_turn(
        self,
        memory_id: str,
        question: str,
        answer: str,
        memory_context: str,
        retrieved_context: str,
        tool_trace: list[dict[str, Any]] | None = None,
    ) -> None:
        record = {
            "timestamp": datetime.utcnow().isoformat(),
            "memory_id": memory_id,
            "question": question,
            "answer": answer,
            "memory_context": memory_context,
            "retrieved_context": retrieved_context,
            "tool_trace": tool_trace or [],
        }
        with self._log_path(memory_id).open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
