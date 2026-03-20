# Zoe 项目 Memory 机制梳理

本文用于快速复习本项目中所有 memory 相关机制，重点回答 3 个问题：

1. memory 存在哪
2. 在哪个时间点写入或压缩
3. 每轮到底以什么格式给模型

## 1. Memory 总览

本项目的 memory 可以分为 3 层。

### 1.1 会话级分层记忆（同一个 memoryId）

- 存储位置：MongoDB 集合 `zoe.layered_memory`（可由环境变量覆盖）
- 代码入口：`py-backend/app/memory_store.py`
- 主键维度：`memory_id`（格式示例：`user_1_mem_311984`）
- 核心字段：
  - `working_memory`
  - `short_term_summary`
  - `session_facts`
  - `tool_working_memory`
  - `last_compressed_at`

用途：承载当前会话近期上下文、会话稳定事实、工具调用槽位状态。

### 1.2 用户级长期结构化画像（跨会话）

- 存储位置：MongoDB 集合 `zoe.user_profiles`
- 代码入口：`py-backend/app/memory_store.py`
- 主键维度：`user_id`
- 核心字段：
  - `profile.identity.patient_name`
  - `profile.identity.id_card`
  - `profile.medical_history`
  - `profile.allergies`
  - `profile.medications`
  - `profile.preferences`
  - `profile.care_plan`
  - `profile.long_term_memory_items`

用途：跨不同 memoryId 复用用户长期信息。

### 1.3 会话日志（回放与排障）

- 存储位置：
  - 本地 JSONL：`py-backend/data/logs/conversation_*.jsonl`
  - MongoDB：`zoe.conversation_sessions`
- 代码入口：`py-backend/app/conversation_logger.py`

用途：会话列表和详情查询、问题排查。不是分层记忆主存储。

## 2. 请求进入后的时间线

聊天请求入口：`POST /zoe/chat`

请求体字段：
- `userId`
- `memoryId`
- `message`

后端先拼接作用域 memoryId：
- `scoped_memory_id = user_{userId}_mem_{memoryId}`

然后执行 LangGraph 固定流程：
- `load_memory` -> `retrieve_docs` -> `generate_answer` -> `save_memory`

### T1 load_memory

- 调用 `memory_store.render_context(memory_id, question)` 生成 `memory_context`
- 调用 `memory_store.is_first_session(memory_id)` 生成首次会话标记

输出到状态：
- `memory_context`
- `is_first_session`

### T2 retrieve_docs

- 调用混合检索器 `retriever.retrieve(question)`
- 将每个文档拼成：
  - `[来源]{source}\n{page_content}`
- 最终拼接为一个大字符串 `retrieved_context`

输出到状态：
- `retrieved_context`

### T3 generate_answer

构建系统提示词：
- 模板文件：`py-backend/prompts/chat_system_prompt.txt`
- 注入变量：
  - `current_date`
  - `is_first_session`
  - `memory_context`
  - `retrieved_context`

用户消息格式：
- `用户问题:\n{question}`

消息结构：
- `SystemMessage(content=system_prompt)`
- `HumanMessage(content=user_prompt)`

若模型支持 function calling：
- 模型可能返回 `tool_calls`
- 后端执行工具后，把结果封装为 `ToolMessage`
- 再回喂模型继续推理（最多 4 轮）
- 本轮工具调用痕迹累计在 `tool_trace`，每项格式：
  - `{"tool": "...", "args": {...}, "result": "..."}`

### T4 save_memory

先写会话级记忆：
- `add_turn(memory_id, question, answer, tool_trace)`
- 具体动作：
  - 追加 2 条 working_memory（user + assistant）
  - 更新 `tool_working_memory`（意图、已收集槽位、缺失槽位、状态、近期工具调用）
  - 依据 `WORKING_MEMORY_WINDOW` 裁剪窗口

再尝试自动压缩：
- `maybe_auto_compress(memory_id)`
- 触发条件：working_memory 合并文本长度 >= `AUTO_COMPRESS_TRIGGER_CHARS`

最后写日志（双写）：
- JSONL：每轮一行
- Mongo 会话集合：用于列表和详情

## 3. 每轮给模型的上下文到底是什么

每轮主问答时，系统提示词里会包含两段关键注入：

- `[记忆上下文]` 对应 `memory_context`
- `[检索上下文]` 对应 `retrieved_context`

其中 `memory_context` 是 `render_context` 生成的纯文本，固定 6 个区块：

1. `[短期摘要]`
2. `[会话稳定事实]`
3. `[函数调用工作记忆]`
4. `[长期记忆检索结果]`
5. `[用户结构化长期记忆]`
6. `[工作记忆]`

这 6 个区块按顺序拼接后，整体替换进系统提示模板中的 `{{memory_context}}`。

`retrieved_context` 则是知识库检索结果拼接文本，替换 `{{retrieved_context}}`。

## 4. 压缩机制细节

### 4.1 触发方式

- 自动触发：每轮 `save_memory` 后检查长度阈值
- 手动触发：`POST /zoe/memory/compress`

### 4.2 压缩输入

- 输入是当前 `working_memory` 展平后的 `history` 文本
- 使用模板：`py-backend/prompts/memory_compress_prompt.txt`

### 4.3 压缩输出解析

后端优先期望模型返回严格 JSON 对象：

- `short_term_summary`
- `session_facts`

解析策略：

- 优先按 JSON 对象解析并写入 `short_term_summary`、`session_facts`
- 兼容旧格式（文本摘要 + JSON 数组）作为回退路径
- 不再解析 `concise_summary` 字段；仅接受 `short_term_summary`
- 对摘要做历史标签清洗后再入库（用于迁移旧脏数据）
- `session_facts` 同步合并进长期条目 `long_term_memory_items`

### 4.4 压缩后的裁剪

- 压缩完成后，`working_memory` 只保留最近 2 轮（4 条消息）

## 5. 用户长期画像抽取

在 `compress` 过程中会额外调用画像抽取：

1. 用 `user_profile_extract_prompt.txt` + 当前历史 + 当前画像
2. 让模型返回严格 JSON：
   - `identity`
   - `medical_history`
   - `allergies`
   - `medications`
   - `preferences`
   - `care_plan`
3. 与现有画像做 merge 去重
4. 回写 `user_profiles`

这一步实现了“跨会话可复用”的结构化长期记忆更新。

## 6. long_term_memory_items 路由检索

`render_context` 时会判断当前问题是否命中长期记忆路由关键词（如“之前、上次、过敏、慢病、按之前”等）。

命中后：
- 在 `user_profiles.long_term_memory_items` 上做 BM25 检索
- 取 TopK（配置项 `LONG_TERM_MEMORY_TOP_K`）
- 结果写入 `[长期记忆检索结果]` 区块

未命中则写固定提示：
- 本轮未命中长期记忆路由或无相关结果

## 7. 字段级对照表（复习版）

### 7.1 layered_memory（会话级）

- `working_memory`
  - 来源：每轮 user/assistant 对话追加
  - 写入时机：`add_turn`
  - 是否进 prompt：是，进入 `[工作记忆]`
- `short_term_summary`
  - 来源：压缩模型输出摘要
  - 写入时机：`compress`
  - 是否进 prompt：是，进入 `[短期摘要]`
- `session_facts`
  - 来源：压缩模型输出事实数组
  - 写入时机：`compress`
  - 是否进 prompt：是，进入 `[会话稳定事实]`
- `tool_working_memory`
  - 来源：每轮根据 `question + tool_trace` 推断
  - 写入时机：`add_turn`
  - 是否进 prompt：是，进入 `[函数调用工作记忆]`

### 7.2 user_profiles（用户级）

- `identity / medical_history / allergies / medications / preferences / care_plan`
  - 来源：画像抽取模型输出 + merge
  - 写入时机：`compress`
  - 是否进 prompt：是，进入 `[用户结构化长期记忆]`
- `long_term_memory_items`
  - 来源：`session_facts` 与画像增量条目同步合并
  - 写入时机：`compress`
  - 是否进 prompt：间接是。仅在命中路由时检索后进入 `[长期记忆检索结果]`

### 7.3 conversation_sessions / JSONL（日志）

- `question / answer / memory_context / retrieved_context / tool_trace`
  - 来源：每轮执行结果
  - 写入时机：`save_memory` 末尾 `log_turn`
  - 是否进 prompt：否（主要用于回放与排障）

## 8. 常见混淆点

### 8.1 为什么看起来有很多 memory

因为系统把“会话即时记忆、用户长期画像、会话日志”拆成了不同职责和不同集合。

### 8.2 哪些会直接影响下一轮回答

会直接影响下一轮主模型回答的是：
- `memory_context`（由 layered_memory + user_profiles + long_term 路由检索拼成）
- `retrieved_context`（知识库检索）

### 8.3 日志和记忆的关系

日志会存下当轮的 memory_context 和 retrieved_context 快照，便于复盘；
但日志本身不是下一轮 prompt 的直接输入源。

## 9. 关键代码索引

- 会话入口与 scoped memoryId：`py-backend/app/main.py`
- 图流程节点：`py-backend/app/graph_flow.py`
- 分层记忆与压缩：`py-backend/app/memory_store.py`
- 会话日志：`py-backend/app/conversation_logger.py`
- 提示词渲染：`py-backend/app/prompt_loader.py`
- 主问答提示词：`py-backend/prompts/chat_system_prompt.txt`
- 记忆压缩提示词：`py-backend/prompts/memory_compress_prompt.txt`
- 用户画像抽取提示词：`py-backend/prompts/user_profile_extract_prompt.txt`

## 10. 复习建议

建议按以下顺序快速过一遍代码：

1. 先看 `main.py` 的 `/zoe/chat` 和 `/zoe/memory/compress`
2. 再看 `graph_flow.py` 的 4 个节点
3. 接着看 `memory_store.py` 的 `render_context -> add_turn -> maybe_auto_compress -> compress`
4. 最后看 `conversation_logger.py` 理解日志双写

这样阅读时最不容易混淆。