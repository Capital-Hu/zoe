from __future__ import annotations

import json
from datetime import date
from typing import Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, StateGraph

from app.agents.tools import get_agent_tools
from app.memory.conversation_logger import ConversationLogger
from app.memory.trajectory_store import TrajectoryStore
from app.utils.prompt_loader import render_prompt


class ChatState(TypedDict, total=False):
    memory_id: str
    question: str
    is_first_session: bool
    memory_context: str
    trajectory_context: str
    retrieved_context: str
    tool_trace: list[dict[str, Any]]
    answer: str


class ZoeGraph:
    def __init__(self, llm, retriever, memory_store):
        self.llm = llm
        self.retriever = retriever
        self.memory_store = memory_store
        self.tools = get_agent_tools()
        self.tool_map = {tool.name: tool for tool in self.tools}
        self.tool_enabled_llm = self._bind_tools(llm)
        self.conversation_logger = ConversationLogger()
        self.trajectory_store = TrajectoryStore()
        self.graph = self._build_graph()

    def _bind_tools(self, llm):
        try:
            return llm.bind_tools(self.tools)
        except Exception:
            return None

    def _build_graph(self):
        workflow = StateGraph(ChatState)
        workflow.add_node("load_memory", self._load_memory)
        workflow.add_node("retrieve_trajectories", self._retrieve_trajectories)
        workflow.add_node("retrieve_docs", self._retrieve_docs)
        workflow.add_node("generate_answer", self._generate_answer)
        workflow.add_node("save_memory", self._save_memory)
        workflow.add_node("reflect", self._reflect)
        workflow.set_entry_point("load_memory")
        workflow.add_edge("load_memory", "retrieve_trajectories")
        workflow.add_edge("retrieve_trajectories", "retrieve_docs")
        workflow.add_edge("retrieve_docs", "generate_answer")
        workflow.add_edge("generate_answer", "save_memory")
        workflow.add_edge("save_memory", "reflect")
        workflow.add_edge("reflect", END)
        return workflow.compile()

    def _load_memory(self, state: ChatState) -> ChatState:
        memory_context = self.memory_store.render_context(state["memory_id"], state.get("question", ""))
        is_first_session = self.memory_store.is_first_session(state["memory_id"])
        return {"memory_context": memory_context, "is_first_session": is_first_session}

    def _retrieve_trajectories(self, state: ChatState) -> ChatState:
        try:
            trajectory_context = self.trajectory_store.render_trajectory_context(
                state.get("question", ""), top_k=2
            )
        except Exception:
            trajectory_context = ""
        return {"trajectory_context": trajectory_context}

    def _retrieve_docs(self, state: ChatState) -> ChatState:
        docs = self.retriever.retrieve(state["question"])
        joined = "\n\n".join([
            f"[来源]{doc.metadata.get('source', 'unknown')}\n{doc.page_content}"
            for doc in docs
        ])
        return {"retrieved_context": joined}

    def _generate_answer(self, state: ChatState) -> ChatState:
        system_prompt = render_prompt(
            "chat_system_prompt.txt",
            current_date=date.today().isoformat(),
            is_first_session="是" if state.get("is_first_session", False) else "否",
            memory_context=state.get("memory_context", ""),
            trajectory_context=state.get("trajectory_context", "") or "暂无历史轨迹",
            retrieved_context=state.get("retrieved_context", ""),
        )
        user_prompt = f"用户问题:\n{state['question']}"
        messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]

        if self.tool_enabled_llm is None:
            response = self.llm.invoke(messages)
            answer = response.content if isinstance(response.content, str) else str(response.content)
            return {"answer": answer}

        max_rounds = 4
        answer = ""
        tool_trace: list[dict[str, Any]] = []
        for _ in range(max_rounds):
            ai_msg = self.tool_enabled_llm.invoke(messages)
            messages.append(ai_msg)
            tool_calls = getattr(ai_msg, "tool_calls", []) or []
            if not tool_calls:
                answer = ai_msg.content if isinstance(ai_msg.content, str) else str(ai_msg.content)
                break

            for call in tool_calls:
                tool_name = call.get("name", "")
                args = call.get("args", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {"input": args}

                tool = self.tool_map.get(tool_name)
                if not tool:
                    tool_result = f"工具 {tool_name} 不存在。"
                else:
                    try:
                        tool_result = str(tool.invoke(args))
                    except Exception as exc:
                        tool_result = f"工具 {tool_name} 执行失败：{exc}"

                tool_trace.append({"tool": tool_name, "args": args, "result": tool_result})
                messages.append(ToolMessage(content=tool_result, tool_call_id=call.get("id", "")))

        if not answer:
            final_msg = self.tool_enabled_llm.invoke(messages)
            answer = final_msg.content if isinstance(final_msg.content, str) else str(final_msg.content)

        return {"answer": answer, "tool_trace": tool_trace}

    def _save_memory(self, state: ChatState) -> ChatState:
        self.memory_store.add_turn(
            state["memory_id"],
            state["question"],
            state.get("answer", ""),
            tool_trace=state.get("tool_trace", []),
        )
        self.memory_store.maybe_auto_compress(state["memory_id"])
        try:
            self.conversation_logger.log_turn(
                memory_id=state["memory_id"],
                question=state.get("question", ""),
                answer=state.get("answer", ""),
                memory_context=state.get("memory_context", ""),
                retrieved_context=state.get("retrieved_context", ""),
                tool_trace=state.get("tool_trace", []),
            )
        except Exception:
            pass
        try:
            self.trajectory_store.annotate_and_store(
                memory_id=state["memory_id"],
                question=state.get("question", ""),
                answer=state.get("answer", ""),
                tool_trace=state.get("tool_trace", []),
            )
        except Exception:
            pass
        return {}

    def _reflect(self, state: ChatState) -> ChatState:
        """Self-reflection node: evaluate the interaction and store strategy notes.

        Only triggers when tool calls were made (decision-making worth reflecting on).
        """
        tool_trace = state.get("tool_trace", [])
        if not tool_trace:
            return {}

        try:
            annotation = self.trajectory_store.get_last_annotation(state["memory_id"])
            outcome = annotation.get("outcome", "unknown") if annotation else "unknown"
            reward = annotation.get("reward", 0.0) if annotation else 0.0

            trace_text = "\n".join(
                f"- {t.get('tool', '')}({t.get('args', {})}) → {str(t.get('result', ''))[:100]}"
                for t in tool_trace
            )
            reflection_prompt = render_prompt(
                "reflection_prompt.txt",
                question=state.get("question", ""),
                answer=state.get("answer", "")[:300],
                tool_trace=trace_text,
                outcome=outcome,
                reward=str(reward),
            )
            res = self.llm.invoke([HumanMessage(content=reflection_prompt)])
            text = res.content if isinstance(res.content, str) else str(res.content)

            parsed = self._extract_json(text)
            if not parsed:
                return {}

            strategy_notes = parsed.get("strategy_notes", [])
            if isinstance(strategy_notes, list) and strategy_notes:
                self.memory_store.add_strategy_notes(state["memory_id"], strategy_notes)

            efficiency_score = parsed.get("efficiency_score", 0)
            improvement = str(parsed.get("improvement", "") or "").strip()
            if efficiency_score and isinstance(efficiency_score, int):
                self.trajectory_store.update_reflection(
                    memory_id=state["memory_id"],
                    efficiency_score=efficiency_score,
                    improvement=improvement,
                )
        except Exception:
            pass
        return {}

    @staticmethod
    def _extract_json(text: str) -> dict:
        left = text.find("{")
        right = text.rfind("}")
        if left == -1 or right == -1 or right <= left:
            return {}
        try:
            import json as _json
            data = _json.loads(text[left : right + 1])
        except (json.JSONDecodeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def run(self, memory_id: str, question: str) -> str:
        result = self.graph.invoke({"memory_id": memory_id, "question": question})
        return result.get("answer", "")

    def run_stream(self, memory_id: str, question: str):
        state: ChatState = {"memory_id": memory_id, "question": question}
        state.update(self._load_memory(state))
        state.update(self._retrieve_trajectories(state))
        state.update(self._retrieve_docs(state))

        system_prompt = render_prompt(
            "chat_system_prompt.txt",
            current_date=date.today().isoformat(),
            is_first_session="是" if state.get("is_first_session", False) else "否",
            memory_context=state.get("memory_context", ""),
            trajectory_context=state.get("trajectory_context", "") or "暂无历史轨迹",
            retrieved_context=state.get("retrieved_context", ""),
        )
        user_prompt = f"用户问题:\n{state['question']}"
        messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]

        llm_to_use = self.tool_enabled_llm or self.llm
        answer_parts: list[str] = []
        tool_trace: list[dict[str, Any]] = []

        max_rounds = 4
        for _ in range(max_rounds):
            gathered = None
            round_tokens: list[str] = []

            for chunk in llm_to_use.stream(messages):
                if gathered is None:
                    gathered = chunk
                else:
                    gathered = gathered + chunk
                if getattr(chunk, "content", None):
                    text = chunk.content if isinstance(chunk.content, str) else str(chunk.content)
                    round_tokens.append(text)
                    yield f"data: {json.dumps({'token': text}, ensure_ascii=False)}\n\n"

            if gathered is None:
                break

            messages.append(gathered)
            tool_calls = getattr(gathered, "tool_calls", []) or []
            if not tool_calls:
                answer_parts.extend(round_tokens)
                break

            for call in tool_calls:
                tool_name = call.get("name", "")
                args = call.get("args", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {"input": args}

                tool = self.tool_map.get(tool_name)
                if not tool:
                    tool_result = f"工具 {tool_name} 不存在。"
                else:
                    try:
                        tool_result = str(tool.invoke(args))
                    except Exception as exc:
                        tool_result = f"工具 {tool_name} 执行失败：{exc}"

                tool_trace.append({"tool": tool_name, "args": args, "result": tool_result})
                messages.append(ToolMessage(content=tool_result, tool_call_id=call.get("id", "")))

        answer = "".join(answer_parts).strip()
        if not answer:
            final_msg = llm_to_use.invoke(messages)
            answer = final_msg.content if isinstance(final_msg.content, str) else str(final_msg.content)
            if answer:
                yield f"data: {json.dumps({'token': answer}, ensure_ascii=False)}\n\n"

        self.memory_store.add_turn(memory_id, question, answer, tool_trace=tool_trace)
        self.memory_store.maybe_auto_compress(memory_id)
        try:
            self.conversation_logger.log_turn(
                memory_id=memory_id,
                question=question,
                answer=answer,
                memory_context=state.get("memory_context", ""),
                retrieved_context=state.get("retrieved_context", ""),
                tool_trace=tool_trace,
            )
        except Exception:
            pass
        try:
            self.trajectory_store.annotate_and_store(
                memory_id=memory_id,
                question=question,
                answer=answer,
                tool_trace=tool_trace,
            )
        except Exception:
            pass
        # Self-reflection (async-safe: runs after [DONE] is not needed, runs before)
        if tool_trace:
            try:
                reflect_state: ChatState = {
                    "memory_id": memory_id,
                    "question": question,
                    "answer": answer,
                    "tool_trace": tool_trace,
                }
                self._reflect(reflect_state)
            except Exception:
                pass
        yield "data: [DONE]\n\n"
