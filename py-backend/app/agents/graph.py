from __future__ import annotations

import json
from queue import Empty, Queue
from threading import Thread
from datetime import date
from typing import Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, StateGraph

from app.agents.tools import get_agent_tools
from app.agents.intent_policy import build_clarification_if_needed
from app.memory.conversation_logger import ConversationLogger, log_llm_call
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
    stream_emitter: Any


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

    def _to_jsonable(self, value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, list):
            return [self._to_jsonable(item) for item in value]
        if isinstance(value, dict):
            return {str(key): self._to_jsonable(item) for key, item in value.items()}
        return str(value)

    def _serialize_message(self, msg: Any) -> dict[str, Any]:
        msg_type = getattr(msg, "type", msg.__class__.__name__)
        content = getattr(msg, "content", "")
        payload: dict[str, Any] = {
            "type": str(msg_type),
            "content": self._to_jsonable(content),
        }
        tool_calls = getattr(msg, "tool_calls", None)
        if tool_calls:
            payload["tool_calls"] = self._to_jsonable(tool_calls)
        additional_kwargs = getattr(msg, "additional_kwargs", None)
        if additional_kwargs:
            payload["additional_kwargs"] = self._to_jsonable(additional_kwargs)
        return payload

    def _serialize_messages(self, messages: list[Any]) -> list[dict[str, Any]]:
        return [self._serialize_message(msg) for msg in messages]

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
        clarification = build_clarification_if_needed(self.memory_store, state["memory_id"], state.get("question", ""))
        if clarification:
            return {"answer": clarification, "tool_trace": []}

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
        stream_emitter = state.get("stream_emitter")
        can_stream = callable(stream_emitter)
        llm_rounds: list[dict[str, Any]] = []

        if can_stream:
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
                        stream_emitter(text)

                if gathered is None:
                    break

                log_llm_call(
                    memory_id=state["memory_id"],
                    call_name="chat.generate_answer.stream_round",
                    request_payload={"messages": self._serialize_messages(messages)},
                    response_payload=self._serialize_message(gathered),
                    metadata={"round": len(llm_rounds) + 1},
                )

                messages.append(gathered)
                tool_calls = getattr(gathered, "tool_calls", []) or []
                round_info: dict[str, Any] = {
                    "round": len(llm_rounds) + 1,
                    "assistant_message": self._serialize_message(gathered),
                    "stream_text": "".join(round_tokens),
                }
                if not tool_calls:
                    llm_rounds.append(round_info)
                    answer_parts.extend(round_tokens)
                    break

                tool_results: list[dict[str, Any]] = []
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
                    tool_results.append({"tool": tool_name, "args": self._to_jsonable(args), "result": tool_result})
                    messages.append(ToolMessage(content=tool_result, tool_call_id=call.get("id", "")))

                round_info["tool_results"] = tool_results
                llm_rounds.append(round_info)

            answer = "".join(answer_parts).strip()
            if not answer:
                final_msg = llm_to_use.invoke(messages)
                answer = final_msg.content if isinstance(final_msg.content, str) else str(final_msg.content)
                if answer:
                    stream_emitter(answer)
                log_llm_call(
                    memory_id=state["memory_id"],
                    call_name="chat.generate_answer.stream_invoke_fallback",
                    request_payload={"messages": self._serialize_messages(messages)},
                    response_payload=self._serialize_message(final_msg),
                    metadata={"round": len(llm_rounds) + 1},
                )
                llm_rounds.append({
                    "round": len(llm_rounds) + 1,
                    "assistant_message": self._serialize_message(final_msg),
                    "invoke_fallback": True,
                })

            return {"answer": answer, "tool_trace": tool_trace}

        if self.tool_enabled_llm is None:
            response = self.llm.invoke(messages)
            answer = response.content if isinstance(response.content, str) else str(response.content)
            log_llm_call(
                memory_id=state["memory_id"],
                call_name="chat.generate_answer.single_invoke",
                request_payload={"messages": self._serialize_messages(messages)},
                response_payload=self._serialize_message(response),
                metadata={"tool_enabled": False},
            )
            return {"answer": answer}

        max_rounds = 4
        answer = ""
        tool_trace: list[dict[str, Any]] = []
        for _ in range(max_rounds):
            ai_msg = self.tool_enabled_llm.invoke(messages)
            log_llm_call(
                memory_id=state["memory_id"],
                call_name="chat.generate_answer.tool_loop_round",
                request_payload={"messages": self._serialize_messages(messages)},
                response_payload=self._serialize_message(ai_msg),
                metadata={"round": len(llm_rounds) + 1},
            )
            messages.append(ai_msg)
            tool_calls = getattr(ai_msg, "tool_calls", []) or []
            round_info: dict[str, Any] = {
                "round": len(llm_rounds) + 1,
                "assistant_message": self._serialize_message(ai_msg),
            }
            if not tool_calls:
                llm_rounds.append(round_info)
                answer = ai_msg.content if isinstance(ai_msg.content, str) else str(ai_msg.content)
                break

            tool_results: list[dict[str, Any]] = []
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
                tool_results.append({"tool": tool_name, "args": self._to_jsonable(args), "result": tool_result})
                messages.append(ToolMessage(content=tool_result, tool_call_id=call.get("id", "")))

            round_info["tool_results"] = tool_results
            llm_rounds.append(round_info)

        if not answer:
            final_msg = self.tool_enabled_llm.invoke(messages)
            answer = final_msg.content if isinstance(final_msg.content, str) else str(final_msg.content)
            log_llm_call(
                memory_id=state["memory_id"],
                call_name="chat.generate_answer.tool_loop_invoke_fallback",
                request_payload={"messages": self._serialize_messages(messages)},
                response_payload=self._serialize_message(final_msg),
                metadata={"round": len(llm_rounds) + 1},
            )
            llm_rounds.append({
                "round": len(llm_rounds) + 1,
                "assistant_message": self._serialize_message(final_msg),
                "invoke_fallback": True,
            })

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
            log_llm_call(
                memory_id=state["memory_id"],
                call_name="chat.reflect.invoke",
                request_payload={"prompt": reflection_prompt},
                response_payload={"content": text},
                metadata={"tool_trace_count": len(tool_trace), "outcome": outcome, "reward": reward},
            )

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
        events: Queue[tuple[str, str]] = Queue()
        emitted = {"count": 0}

        def stream_emitter(token: str) -> None:
            if not token:
                return
            emitted["count"] += 1
            events.put(("token", token))

        def worker() -> None:
            try:
                result = self.graph.invoke(
                    {"memory_id": memory_id, "question": question, "stream_emitter": stream_emitter}
                )
                answer = result.get("answer", "") if isinstance(result, dict) else ""
                if answer and emitted["count"] == 0:
                    events.put(("token", answer))
            except Exception:
                events.put(("error", ""))
            finally:
                events.put(("done", ""))

        t = Thread(target=worker, daemon=True)
        t.start()

        while True:
            try:
                event, payload = events.get(timeout=0.2)
            except Empty:
                if t.is_alive():
                    continue
                break

            if event == "token":
                yield f"data: {json.dumps({'token': payload}, ensure_ascii=False)}\n\n"
                continue
            if event == "error":
                yield f"data: {json.dumps({'token': '系统繁忙，请稍后再试。'}, ensure_ascii=False)}\n\n"
                continue
            if event == "done":
                break

        yield "data: [DONE]\n\n"
