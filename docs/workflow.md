# Zoe Chat Workflow

本文聚焦 `ZoeGraph` 的执行流程，覆盖同步/流式聊天路径、前置意图路由与澄清、工具调用循环、记忆写入与反思阶段。

## 1. 相关代码位置

- 图编排与主流程：`py-backend/app/agents/graph.py`
- 前置意图路由、槽位状态维护与追问策略：`py-backend/app/agents/intent_policy.py`
- 会话记忆读写：`py-backend/app/memory/layered_store.py`
- 会话日志：`py-backend/app/memory/conversation_logger.py`
- 轨迹存储与反思标注：`py-backend/app/memory/trajectory_store.py`
- 主系统提示词：`py-backend/prompts/chat_system_prompt.txt`

## 2. 一句话概览

每轮聊天会先加载记忆，然后在调用主 LLM 前执行“前置意图路由 + 澄清策略”：先根据最近上下文、上一轮工具状态和当前话术判断用户正在做什么，再决定是否需要追问补槽；如果仍然无法确定，再交给受限的意图路由模型兜底。对于“谢谢/好的/嗯”这类短闲聊，系统会优先保持会话自然流转，不强制触发补槽位追问。

## 3. 主流程图（含前置澄清）

```mermaid
flowchart TD
  A[POST /zoe/chat] --> B[构造 scoped memory_id]
  B --> C[load_memory]
  C --> D{build_clarification_if_needed}
  D -- 需要澄清 --> D1[直接返回追问]
  D1 --> D2[add_turn + log_turn]
  D2 --> Z[[DONE]]

  D -- 不需要澄清 --> E[retrieve_trajectories]
  E --> F[retrieve_docs]
  F --> G[generate_answer]
  G --> H{是否有 tool_calls}
  H -- 否 --> I[answer]
  H -- 是 --> J[执行工具]
  J --> K[ToolMessage 回喂模型]
  K --> H

  I --> L[save_memory]
  L --> M[maybe_auto_compress]
  M --> N[log_turn]
  N --> O[annotate_and_store trajectory]
  O --> P{tool_trace 非空}
  P -- 是 --> Q[reflect]
  P -- 否 --> Z
  Q --> Z
```

## 4. LangGraph 节点顺序

`graph.invoke(...)` 的固定节点顺序是：

1. `load_memory`
2. `retrieve_trajectories`
3. `retrieve_docs`
4. `generate_answer`
5. `save_memory`
6. `reflect`

说明：

- `reflect` 节点内部只在有工具调用时做实际反思。
- 流式接口 `run_stream(...)` 也通过 `graph.invoke(...)` 执行同一套节点流程，仅在 `generate_answer` 节点内通过回调发出 SSE token。

## 5. 前置意图澄清策略

执行入口：`build_clarification_if_needed(memory_store, memory_id, question)`。

### 5.1 触发条件

1. 用户问题为空：直接追问用户想做的流程类型。
2. 同时命中多个流程意图（且不存在可继承的上一轮 intent）：先让用户确认流程。
3. 当前话术没有明显关键词，但最近上下文已经在某个就医流程中：会先尝试继承上一轮 intent，再结合短回复判断是否继续补槽。
4. 已识别流程但必填字段未收齐：先追问缺失字段，再继续。
5. 上一轮处于 `collecting_slots/ready/tool_called`：即使本轮只回复字段值（如身份证号、上午/下午），也会沿用上一轮 intent 继续补槽。
6. 若用户仅发送短闲聊（如“谢谢”“好的”）：
  - 当前处于活跃流程时，不会清空 intent，也不会立刻追问槽位（避免打断对话节奏）。
  - 当前不在活跃流程时，会保持/回到 `idle`。

### 5.2 当前支持的流程意图

- `recommend_department`
- `check_registration_slots`
- `book_appointment`
- `cancel_appointment`
- `query_appointment_records`

### 5.3 槽位缺失追问示例

当用户说“帮我挂号”但未给身份证号/日期/时段时，系统会返回“还需要补充哪些字段”的追问，不会直接触发工具。

### 5.4 意图识别状态机

下面改成两张简化图：

1. 路由判定（中间逻辑）
2. 持久化状态机（真正写入 `tool_working_memory.status`）

```mermaid
flowchart TD
  A[收到用户输入] --> B{短闲聊?}
  B -- 是 --> C{当前是否活跃流程?}
  C -- 是 --> K[保持原状态]
  C -- 否 --> I[idle]

  B -- 否 --> D{关键词/上下文可判定?}
  D -- 是 --> E[得到 intent]
  D -- 否 --> F[LLM 路由兜底]
  F --> G{intent=none?}
  G -- 是 --> I[idle]
  G -- 否 --> E

  E --> H{槽位是否齐全?}
  H -- 否 --> J[collecting_slots]
  H -- 是 --> R[ready]
```

```mermaid
stateDiagram-v2
  [*] --> idle
  idle --> collecting_slots: 识别到流程且缺槽位
  idle --> ready: 识别到流程且槽位齐全

  collecting_slots --> collecting_slots: 持续补槽/短闲聊不打断
  collecting_slots --> ready: 槽位补齐

  ready --> tool_called: 执行工具
  tool_called --> collecting_slots: 工具后仍缺槽位
  tool_called --> ready: 同流程继续

  idle --> idle: 非流程对话/none
  collecting_slots --> idle: 明确退出流程
  ready --> idle: 流程结束
  tool_called --> idle: 流程结束
```

补充说明：

- 中间态（如多意图确认）属于路由逻辑，不落库。
- 持久化状态仅关注 `idle / collecting_slots / ready / tool_called`。

## 6. 工具调用循环

在 `generate_answer` 阶段：

1. 使用 `tool_enabled_llm`（若模型支持 `bind_tools`）进行推理。
2. 最多循环 `max_rounds = 4`。
3. 每次有 `tool_calls` 时逐个执行工具，并将结果组装为 `ToolMessage` 回喂模型。
4. 无 `tool_calls` 时收敛为最终回答。

## 7. 记忆与日志写入时机

正常回答路径下：

1. `add_turn(...)`：写入工作记忆与工具工作记忆。
2. `maybe_auto_compress(...)`：达到阈值时触发压缩，更新摘要与会话事实。
3. `log_turn(...)`：写 JSONL + Mongo 会话日志。
4. `annotate_and_store(...)`：写轨迹缓冲区，供后续经验检索。

前置澄清路径下：

- 同样会执行 `add_turn(...)` 和 `log_turn(...)`，保证追问本身也进入会话上下文。
- `tool_working_memory` 也会被更新并持久化，确保下一轮即使没有关键词，也能继续沿用同一个意图状态。

## 8. 同步与流式差异

- `run(...)`：调用 `graph.invoke(...)`，一次性返回完整 answer。
- `run_stream(...)`：后台线程调用 `graph.invoke(...)`，前台以 SSE 分片输出 token，结束时输出 `data: [DONE]`。
- 两者都在 LLM 主流程前执行前置澄清策略；若命中澄清，都会短路返回追问。

## 9. 维护建议

1. 规则迭代优先改 `intent_policy.py`，避免污染编排层。
2. 新增流程意图时，同步更新：关键词、必填字段、字段文案、前置路由提示词。
3. 推荐为 `intent_policy.py` 增加单元测试，覆盖：
   - 多意图冲突
   - 上下文继承 intent
   - 纯槽位回复续流程
   - 缺失字段追问文案
  - 无关键词但有上下文时的意图路由
  - 短闲聊在活跃流程中不打断状态
