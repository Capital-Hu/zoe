"""Trajectory store for In-Context RL.

Stores interaction trajectories with auto-annotated outcomes in MongoDB.
Retrieves high-reward similar trajectories for prompt injection.
"""

from __future__ import annotations

import re
from datetime import datetime
from importlib import import_module
from typing import Any

import jieba
from rank_bm25 import BM25Okapi

from app.core.config import settings


class TrajectoryStore:
    """Stores annotated trajectories and retrieves similar successful ones."""

    def __init__(self):
        try:
            mongo_module = import_module("pymongo")
            mongo_client_cls = getattr(mongo_module, "MongoClient")
        except ModuleNotFoundError as exc:
            raise RuntimeError("pymongo is required") from exc

        client = mongo_client_cls(settings.mongo_uri, serverSelectionTimeoutMS=settings.mongo_timeout_ms)
        client.admin.command("ping")
        self._collection = client[settings.mongo_db][settings.mongo_trajectory_collection]
        self._collection.create_index("memory_id")
        self._collection.create_index("user_id")
        self._collection.create_index([("reward", -1)])
        self._collection.create_index([("outcome", 1), ("reward", -1)])

    # ------------------------------------------------------------------
    # Outcome annotation
    # ------------------------------------------------------------------

    _SUCCESS_KEYWORDS = ("预约成功", "挂号成功", "已成功", "取消成功", "已取消")
    _FAILURE_KEYWORDS = ("失败", "不存在", "不可预约", "无号源", "已停诊", "没有找到", "无法")
    _RETRY_SUCCESS_KEYWORDS = ("重新", "再次", "已修正")

    def _compute_outcome(self, tool_trace: list[dict[str, Any]], answer: str) -> str:
        """Classify the interaction outcome.

        Returns one of: success | failure | partial | retry_success | no_tool
        """
        if not tool_trace:
            return "no_tool"

        results = [str(t.get("result", "") or "") for t in tool_trace]
        has_success = any(kw in r for r in results for kw in self._SUCCESS_KEYWORDS)
        has_failure = any(kw in r for r in results for kw in self._FAILURE_KEYWORDS)
        has_retry = any(kw in r for r in results for kw in self._RETRY_SUCCESS_KEYWORDS)

        if has_success and has_failure:
            return "retry_success" if has_retry else "partial"
        if has_success:
            return "success"
        if has_failure:
            return "failure"
        return "success" if answer.strip() else "failure"

    def _compute_per_step_rewards(self, tool_trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Compute per-tool-call reward signals."""
        step_rewards = []
        for t in tool_trace:
            result = str(t.get("result", "") or "")
            tool_name = str(t.get("tool", "") or "")
            step_outcome = "neutral"
            step_reward = 0.3

            if any(kw in result for kw in self._SUCCESS_KEYWORDS):
                step_outcome = "success"
                step_reward = 1.0
            elif any(kw in result for kw in self._FAILURE_KEYWORDS):
                step_outcome = "failure"
                step_reward = 0.0

            step_rewards.append({
                "tool": tool_name,
                "step_outcome": step_outcome,
                "step_reward": round(step_reward, 3),
            })
        return step_rewards

    def _compute_reward(self, outcome: str, tool_trace: list[dict[str, Any]]) -> float:
        """Compute a scalar reward signal with efficiency and retry bonuses."""
        base_rewards = {
            "success": 1.0,
            "retry_success": 0.6,
            "partial": 0.5,
            "failure": 0.0,
            "no_tool": 0.5,
        }
        reward = base_rewards.get(outcome, 0.0)
        # Efficiency bonus: fewer tool calls = better (max 0.2 bonus)
        if tool_trace:
            efficiency_bonus = min(0.2, 0.2 / max(1, len(tool_trace)))
            reward += efficiency_bonus
        return round(min(reward, 1.0), 3)

    def _parse_scoped_memory(self, memory_id: str) -> tuple[int | None, str]:
        match = re.match(r"^user_(\d+)_mem_(.+)$", memory_id)
        if not match:
            return None, memory_id
        return int(match.group(1)), match.group(2)

    # ------------------------------------------------------------------
    # Store
    # ------------------------------------------------------------------

    def annotate_and_store(
        self,
        memory_id: str,
        question: str,
        answer: str,
        tool_trace: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Annotate outcome/reward and persist the trajectory."""
        outcome = self._compute_outcome(tool_trace, answer)
        reward = self._compute_reward(outcome, tool_trace)
        step_rewards = self._compute_per_step_rewards(tool_trace)
        user_id, _ = self._parse_scoped_memory(memory_id)
        now = datetime.utcnow().isoformat()

        # Build a compact tool summary for retrieval
        tool_summary = []
        for i, t in enumerate(tool_trace):
            entry = {
                "tool": str(t.get("tool", "")),
                "args": t.get("args", {}),
                "result_snippet": str(t.get("result", ""))[:150],
            }
            if i < len(step_rewards):
                entry["step_reward"] = step_rewards[i]["step_reward"]
                entry["step_outcome"] = step_rewards[i]["step_outcome"]
            tool_summary.append(entry)

        doc = {
            "memory_id": memory_id,
            "user_id": user_id,
            "question": question,
            "answer": answer[:500],
            "tool_trace": tool_summary,
            "tool_count": len(tool_trace),
            "outcome": outcome,
            "reward": reward,
            "step_rewards": step_rewards,
            "reflection": None,
            "created_at": now,
        }
        self._collection.insert_one(doc)
        return {"outcome": outcome, "reward": reward}

    def get_last_annotation(self, memory_id: str) -> dict[str, Any] | None:
        """Get the most recent trajectory annotation for a memory_id."""
        doc = self._collection.find_one(
            {"memory_id": memory_id},
            {"_id": 0, "outcome": 1, "reward": 1, "step_rewards": 1},
            sort=[("created_at", -1)],
        )
        return doc

    def update_reflection(
        self,
        memory_id: str,
        efficiency_score: int,
        improvement: str = "",
    ) -> None:
        """Attach reflection data to the most recent trajectory for this memory_id."""
        doc = self._collection.find_one(
            {"memory_id": memory_id},
            {"_id": 1},
            sort=[("created_at", -1)],
        )
        if doc:
            self._collection.update_one(
                {"_id": doc["_id"]},
                {"$set": {
                    "reflection": {
                        "efficiency_score": min(max(efficiency_score, 1), 5),
                        "improvement": improvement[:200],
                        "reflected_at": datetime.utcnow().isoformat(),
                    },
                }},
            )

    # ------------------------------------------------------------------
    # Retrieve similar high-reward trajectories
    # ------------------------------------------------------------------

    def retrieve_similar(
        self,
        question: str,
        top_k: int = 2,
        min_reward: float = 0.5,
        limit_candidates: int = 100,
    ) -> list[dict[str, Any]]:
        """BM25-based retrieval of similar successful trajectories."""
        if not question.strip():
            return []

        # Fetch recent high-reward trajectories as candidates
        cursor = (
            self._collection.find(
                {"reward": {"$gte": min_reward}, "tool_count": {"$gt": 0}},
                {
                    "_id": 0, "question": 1, "answer": 1, "tool_trace": 1,
                    "outcome": 1, "reward": 1, "step_rewards": 1, "reflection": 1,
                },
            )
            .sort("created_at", -1)
            .limit(limit_candidates)
        )
        candidates = list(cursor)
        if not candidates:
            return []

        # BM25 ranking
        texts = [c["question"] for c in candidates]
        tokenized = [list(jieba.cut(t)) for t in texts]
        bm25 = BM25Okapi(tokenized)
        scores = bm25.get_scores(list(jieba.cut(question)))

        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        # Use relative threshold: pick top-k with score above median
        if not ranked:
            return []
        median_score = sorted(scores)[len(scores) // 2] if len(scores) > 2 else float("-inf")
        results = []
        for idx in ranked[:top_k]:
            if scores[idx] > median_score or len(candidates) <= top_k:
                results.append(candidates[idx])
        return results

    def render_trajectory_context(self, question: str, top_k: int = 2) -> str:
        """Render retrieved trajectories as prompt-injectable text."""
        trajectories = self.retrieve_similar(question, top_k=top_k)
        if not trajectories:
            return ""

        blocks = []
        for i, traj in enumerate(trajectories, 1):
            tool_lines = []
            for t in traj.get("tool_trace", []):
                step_info = ""
                if "step_reward" in t:
                    step_info = f" [reward={t['step_reward']}]"
                tool_lines.append(f"  调用 {t['tool']}({t.get('args', {})}) → {t.get('result_snippet', '')}{step_info}")
            tool_text = "\n".join(tool_lines) if tool_lines else "  无工具调用"

            reflection = traj.get("reflection")
            reflection_text = ""
            if reflection and isinstance(reflection, dict):
                eff = reflection.get("efficiency_score", "")
                imp = reflection.get("improvement", "")
                if eff:
                    reflection_text += f"\n  效率评分: {eff}/5"
                if imp:
                    reflection_text += f"\n  改进建议: {imp}"

            blocks.append(
                f"案例{i}（结果: {traj['outcome']}，reward: {traj['reward']}）:\n"
                f"  用户问题: {traj['question']}\n"
                f"  工具调用:\n{tool_text}\n"
                f"  助手回复: {traj['answer'][:200]}"
                f"{reflection_text}"
            )
        return "\n\n".join(blocks)
