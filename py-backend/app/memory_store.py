from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from langchain_core.messages import HumanMessage

from app.config import settings
from app.prompt_loader import render_prompt


class LayeredMemoryStore:
    def __init__(self, llm):
        self.llm = llm
        settings.memory_dir.mkdir(parents=True, exist_ok=True)

    def _safe_memory_id(self, memory_id: str) -> str:
        return "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in str(memory_id))

    def _file(self, memory_id: str) -> Path:
        return settings.memory_dir / f"{self._safe_memory_id(memory_id)}.json"

    def _default(self) -> dict:
        return {
            "working_memory": [],
            "short_term_summary": "",
            "long_term_facts": [],
            "last_compressed_at": None,
        }

    def load(self, memory_id: str) -> dict:
        path = self._file(memory_id)
        if not path.exists():
            return self._default()
        return json.loads(path.read_text(encoding="utf-8"))

    def save(self, memory_id: str, data: dict) -> None:
        self._file(memory_id).write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add_turn(self, memory_id: str, user_msg: str, ai_msg: str) -> None:
        data = self.load(memory_id)
        now = datetime.utcnow().isoformat()
        data["working_memory"].append({"role": "user", "content": user_msg, "ts": now})
        data["working_memory"].append({"role": "assistant", "content": ai_msg, "ts": now})

        # 保留工作记忆窗口
        max_items = settings.working_memory_window * 2
        data["working_memory"] = data["working_memory"][-max_items:]

        self.save(memory_id, data)

    def render_context(self, memory_id: str) -> str:
        data = self.load(memory_id)
        working_lines = [f"{m['role']}: {m['content']}" for m in data["working_memory"]]
        working_text = "\n".join(working_lines) if working_lines else "暂无"
        long_term = "\n".join(f"- {x}" for x in data["long_term_facts"])
        return (
            "[短期摘要]\n"
            f"{data['short_term_summary'] or '暂无'}\n\n"
            "[长期记忆]\n"
            f"{long_term or '- 暂无'}\n\n"
            "[工作记忆]\n"
            f"{working_text}"
        )

    def is_first_session(self, memory_id: str) -> bool:
        data = self.load(memory_id)
        has_working = len(data.get("working_memory", [])) > 0
        has_summary = bool(data.get("short_term_summary", "").strip())
        has_facts = len(data.get("long_term_facts", [])) > 0
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
            merged = data["long_term_facts"] + facts
            # 去重并限长
            seen: set[str] = set()
            deduped: list[str] = []
            for item in merged:
                key = item.strip()
                if key and key not in seen:
                    seen.add(key)
                    deduped.append(key)
            data["long_term_facts"] = deduped[:50]

        # 压缩后只保留最近两轮在工作记忆中
        data["working_memory"] = data["working_memory"][-4:]
        data["last_compressed_at"] = datetime.utcnow().isoformat()
        self.save(memory_id, data)
        return data
