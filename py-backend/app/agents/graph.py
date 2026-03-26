from __future__ import annotations

import json
from datetime import date
from typing import Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, StateGraph

from app.agents.tools import get_agent_tools
from app.memory.conversation_logger import ConversationLogger
from app.utils.prompt_loader import render_prompt


class ChatState(TypedDict, total=False):
    memory_id: str
    question: str
    is_first_session: bool
    memory_context: str
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
        self.graph = self._build_graph()

    def _bind_tools(self, llm):
        try:
            return llm.bind_tools(self.tools)
        except Exception:
            return None

    def _build_graph(self):
        workflow = StateGraph(ChatState)
        workflow.add_node("load_memory", self._load_memory)
        workflow.add_node("retrieve_docs", self._retrieve_docs)
        workflow.add_node("generate_answer", self._generate_answer)
        workflow.add_node("save_memory", self._save_memory)
        workflow.set_entry_point("load_memory")
        workflow.add_edge("load_memory", "retrieve_docs")
        workflow.add_edge("retrieve_docs", "generate_answer")
        workflow.add_edge("generate_answer", "save_memory")
        workflow.add_edge("save_memory", END)
        return workflow.compile()

    def _load_memory(self, state: ChatState) -> ChatState:
        memory_context = self.memory_store.render_context(state["memory_id"], state.get("question", ""))
        is_first_session = self.memory_store.is_first_session(state["memory_id"])
        return {"memory_context": memory_context, "is_first_session": is_first_session}

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
        return {}

    def run(self, memory_id: str, question: str) -> str:
        result = self.graph.invoke({"memory_id": memory_id, "question": question})
        return result.get("answer", "")

    def run_stream(self, memory_id: str, question: str):
        state: ChatState = {"memory_id": memory_id, "question": question}
        state.update(self._load_memory(state))
        state.update(self._retrieve_docs(state))

        system_prompt = render_prompt(
            "chat_system_prompt.txt",
            current_date=date.today().isoformat(),
            is_first_session="是" if state.get("is_first_session", False) else "否",
            memory_context=state.get("memory_context", ""),
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
        yield "data: [DONE]\n\n"
