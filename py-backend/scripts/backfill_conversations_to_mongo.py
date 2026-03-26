from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.config import settings


def safe_memory_id(memory_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in str(memory_id))


def parse_scoped_memory(memory_id: str) -> tuple[int | None, str]:
    match = re.match(r"^user_(\d+)_mem_(.+)$", memory_id)
    if not match:
        return None, memory_id
    return int(match.group(1)), match.group(2)


def main() -> None:
    try:
        from pymongo import MongoClient
    except ModuleNotFoundError:
        print("missing dependency: pymongo")
        print("please run: pip install -r requirements.txt")
        return

    logs_dir = settings.logs_dir
    if not logs_dir.exists():
        print(f"logs dir not found: {logs_dir}")
        return

    client = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=settings.mongo_timeout_ms)
    client.admin.command("ping")
    collection = client[settings.mongo_db][settings.mongo_conversation_collection]
    collection.create_index([("user_id", 1), ("updated_at", -1)])
    collection.create_index("memory_id", unique=True)

    migrated = 0
    skipped = 0

    for log_file in sorted(logs_dir.glob("conversation_*.jsonl")):
        records = []
        with log_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        if not records:
            skipped += 1
            continue

        scoped_memory = str(records[-1].get("memory_id") or "")
        if not scoped_memory:
            skipped += 1
            continue

        user_id, memory_suffix = parse_scoped_memory(scoped_memory)
        if user_id is None:
            skipped += 1
            continue

        messages = []
        for row in records:
            question = str(row.get("question") or "")
            answer = str(row.get("answer") or "")
            ts = str(row.get("timestamp") or "")
            if question:
                messages.append({"role": "user", "content": question, "ts": ts})
            if answer:
                messages.append({"role": "assistant", "content": answer, "ts": ts})

        first_ts = str(records[0].get("timestamp") or "")
        last_ts = str(records[-1].get("timestamp") or "")
        first_question = str(records[0].get("question") or "新会话")
        last_question = str(records[-1].get("question") or "")
        last_answer = str(records[-1].get("answer") or "")

        memory_id = safe_memory_id(scoped_memory)
        update_doc = {
            "$set": {
                "memory_id": memory_id,
                "memory_suffix": memory_suffix,
                "user_id": user_id,
                "title": first_question[:40],
                "turns": len(records),
                "messages": messages,
                "last_question": last_question,
                "last_answer": last_answer,
                "updated_at": last_ts,
            },
            "$setOnInsert": {
                "created_at": first_ts,
            },
        }
        collection.update_one({"memory_id": memory_id}, update_doc, upsert=True)
        migrated += 1

    print(f"migrated={migrated}, skipped={skipped}, collection={settings.mongo_conversation_collection}")


if __name__ == "__main__":
    main()
