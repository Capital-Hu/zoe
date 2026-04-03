"""Smoke test for trajectory store + reflection (In-Context RL)."""

from app.memory.trajectory_store import TrajectoryStore
from app.memory.layered_store import LayeredMemoryStore

ts = TrajectoryStore()

# --- Outcome annotation ---
trace_success = [{"tool": "book_appointment", "args": {"department": "神经内科"}, "result": "预约成功！"}]
trace_failure = [{"tool": "book_appointment", "args": {}, "result": "预约失败：无号源"}]
trace_retry = [
    {"tool": "check_registration_slots", "args": {}, "result": "无号源"},
    {"tool": "check_registration_slots", "args": {}, "result": "已成功 重新查询"},
]
trace_empty = []

assert ts._compute_outcome(trace_success, "已预约") == "success"
assert ts._compute_outcome(trace_failure, "") == "failure"
assert ts._compute_outcome(trace_empty, "hello") == "no_tool"
assert ts._compute_outcome(trace_retry, "查到了") == "retry_success"
print("Outcome annotation OK (including retry_success)")

# --- Per-step rewards ---
step_rewards = ts._compute_per_step_rewards(trace_retry)
assert len(step_rewards) == 2
assert step_rewards[0]["step_outcome"] == "failure"
assert step_rewards[1]["step_outcome"] == "success"
print(f"Per-step rewards: {step_rewards}")

# --- Reward ---
r1 = ts._compute_reward("success", trace_success)
r2 = ts._compute_reward("failure", trace_failure)
r3 = ts._compute_reward("retry_success", trace_retry)
r4 = ts._compute_reward("no_tool", trace_empty)
print(f"Rewards: success={r1}, failure={r2}, retry={r3}, no_tool={r4}")
assert r1 > r3 > r2

# --- Store with per-step rewards ---
result = ts.annotate_and_store(
    memory_id="user_999_mem_test_icrl_v2",
    question="我想挂神经内科明天上午的号",
    answer="好的，已为您成功预约神经内科明天上午的号。",
    tool_trace=trace_success,
)
print(f"Stored trajectory: {result}")
assert result["outcome"] == "success"

# --- get_last_annotation ---
annotation = ts.get_last_annotation("user_999_mem_test_icrl_v2")
assert annotation is not None
assert annotation["outcome"] == "success"
assert "step_rewards" in annotation
print(f"Last annotation: outcome={annotation['outcome']}, reward={annotation['reward']}")

# --- update_reflection ---
ts.update_reflection(
    memory_id="user_999_mem_test_icrl_v2",
    efficiency_score=4,
    improvement="可以先确认日期再查号源",
)
updated = ts._collection.find_one(
    {"memory_id": "user_999_mem_test_icrl_v2"},
    {"_id": 0, "reflection": 1},
    sort=[("created_at", -1)],
)
assert updated["reflection"] is not None
assert updated["reflection"]["efficiency_score"] == 4
print(f"Reflection stored: {updated['reflection']}")

# --- Retrieve ---
retrieved = ts.retrieve_similar("帮我挂神经内科的号", top_k=2)
print(f"Retrieved {len(retrieved)} trajectories")

# --- Render with step rewards + reflection ---
ctx = ts.render_trajectory_context("帮我挂神经内科的号")
print(f"Rendered context ({len(ctx)} chars):\n{ctx[:500]}")
assert "reward=" in ctx or "案例" in ctx

# --- Strategy notes in LayeredMemoryStore ---
# (We can't fully test this without LLM, but test the add_strategy_notes method)
from unittest.mock import MagicMock
mock_llm = MagicMock()
lms = LayeredMemoryStore.__new__(LayeredMemoryStore)
lms.llm = mock_llm
# Use the real mongo connection from settings
from importlib import import_module
from app.core.config import settings
mongo_module = import_module("pymongo")
mongo_client_cls = getattr(mongo_module, "MongoClient")
client = mongo_client_cls(settings.mongo_uri, serverSelectionTimeoutMS=settings.mongo_timeout_ms)
lms._session_collection = client[settings.mongo_db][settings.mongo_memory_collection]
lms._profile_collection = client[settings.mongo_db][settings.mongo_user_profile_collection]
lms._client = client

# Test add_strategy_notes
test_mem_id = "user_999_mem_strategy_test"
lms.save(test_mem_id, lms._default())
lms.add_strategy_notes(test_mem_id, ["用户已给出科室时无需调用recommend_department", "查号源前应确认日期格式"])
data = lms.load(test_mem_id)
assert len(data["strategy_notes"]) == 2
print(f"Strategy notes stored: {data['strategy_notes']}")

# Verify render_context includes strategy notes
ctx = lms.render_context(test_mem_id)
assert "策略反思笔记" in ctx
assert "recommend_department" in ctx
print("render_context includes strategy notes OK")

# Cleanup
lms._session_collection.delete_one({"memory_id": lms._safe_memory_id(test_mem_id)})
ts._collection.delete_many({"memory_id": "user_999_mem_test_icrl_v2"})
print("\nCleaned up test data")
print("All In-Context RL tests PASSED!")
