# Zoe Python Backend (LangChain + LangGraph)

这个目录是新的后端实现，替代原有 Java LangChain4j 对话后端。

## 功能

- 流式聊天接口：`POST /zoe/chat`，入参 `{ "userId": 1, "memoryId": "123", "message": "你好" }`
- 手动压缩记忆接口：`POST /zoe/memory/compress`，入参 `{ "userId": 1, "memoryId": "123" }`
- 分层记忆：函数调用工作记忆 + 会话短期记忆 + 长期记忆轻路由检索 + 用户结构化长期记忆
- 自动记忆压缩：按 `AUTO_COMPRESS_TRIGGER_CHARS` 阈值触发，默认 2200 字符
- 提示词外置：统一放在 `py-backend/prompts/`
- Agent Function Calling：分导诊、查号源、预约、取消预约、记录查询
- In-Context RL：轨迹标注 + 历史成功轨迹检索注入 + Self-Reflection 策略反思
- 业务数据表：用户表、医生排班表、预约表（SQLite）

## 目录结构

当前后端代码不再平铺在 `app/` 根目录，而是按职责拆分：

- `app/main.py`：应用入口，只负责装配 FastAPI、启动依赖、挂载路由
- `app/api/`：HTTP 路由与依赖
- `app/agents/`：LangGraph 流程和 function calling 工具
- `app/core/`：配置、安全等基础能力
- `app/db/`：SQLAlchemy 模型、引擎、会话
- `app/memory/`：会话记忆、会话日志与轨迹存储
- `app/retrieval/`：知识库混合检索
- `app/llm/`：聊天模型与 embedding 模型装配
- `app/schemas/`：Pydantic 请求模型
- `app/utils/`：提示词加载等通用工具

如果你要新增接口，优先在 `app/api/routes/` 下加路由；如果你要改 memory，优先在 `app/memory/` 下处理；如果你要改 Agent 工具链路，优先看 `app/agents/`。

## 环境搭建（Conda）

```bash
cd py-backend
conda create -n zoe python=3.11 -y
conda activate zoe
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

如果终端未自动加载 conda，可改用：

```bash
conda run -n zoe pip install -r requirements.txt
```

按需修改 `.env`：

- 使用 DashScope/OpenAI 兼容接口：
  - `MODEL_PROVIDER=openai_compatible`
  - 配置 `OPENAI_API_KEY`、`OPENAI_BASE_URL`、`CHAT_MODEL`、`EMBEDDING_MODEL`
- 使用 Ollama：
  - `MODEL_PROVIDER=ollama`
  - 配置 `OLLAMA_BASE_URL`、`OLLAMA_CHAT_MODEL`、`OLLAMA_EMBED_MODEL`
- 记忆存储（MongoDB）：
  - `MONGO_URI=mongodb://localhost:27017`
  - `MONGO_DB=zoe`
  - `MONGO_MEMORY_COLLECTION=layered_memory`
  - `MONGO_CONVERSATION_COLLECTION=conversation_sessions`
  - `MONGO_USER_PROFILE_COLLECTION=user_profiles`
  - `MONGO_TRAJECTORY_COLLECTION=trajectory_buffer`
  - `LONG_TERM_MEMORY_TOP_K=3`
  - `MONGO_TIMEOUT_MS=3000`

### macOS 启动 MongoDB（Homebrew）

```bash
brew services start mongodb-community
brew services list | grep mongo
```

如果你还没安装 MongoDB Community：

```bash
brew tap mongodb/brew
brew install mongodb-community
```

## 启动

```bash
cd py-backend
conda activate zoe
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

## 知识库预处理（Embedding + BM25）

在首次启动前建议先做预处理，提前生成向量索引和 BM25 缓存，减少服务冷启动耗时。

`scripts/preprocess_knowledge.py` 当前为全量重建模式：若 `py-backend/data/vector_store/` 已存在，会先删除旧产物再重新生成。

```bash
cd py-backend
conda activate zoe
PYTHONPATH=. python scripts/preprocess_knowledge.py
```

产物文件位于 `py-backend/data/vector_store/`：

- `index.faiss`（向量索引）
- `index.pkl`（FAISS 元信息）
- `bm25_meta.json`（BM25 文档片段）
- `bm25.pkl`（BM25 缓存模型）

## 会话日志

每轮 `/zoe/chat` 会自动保存上下文日志（JSONL）：

- 目录：`py-backend/data/logs/`
- 文件：`conversation_{memoryId}.jsonl`

单条日志包含：

- `timestamp`
- `memory_id`
- `question`
- `answer`
- `memory_context`
- `retrieved_context`
- `tool_trace`（工具名、入参、结果）

如果你已存在历史 JSONL 会话数据，且希望 `/zoe/sessions` 接口可查询到旧数据，可执行一次回填：

```bash
cd py-backend
conda activate zoe
PYTHONPATH=. python scripts/backfill_conversations_to_mongo.py
```

## 数据库与 Mock 数据

SQLite 数据库文件：`py-backend/data/zoe.db`

初始化建库并写入示例数据：

```bash
cd py-backend
conda activate zoe
PYTHONPATH=. python scripts/seed_mock_data.py
```

说明：

- 脚本文件：`py-backend/scripts/seed_mock_data.py`
- 脚本会先重建表结构再写入 mock 数据（便于开发阶段迁移）
- 默认写入：
  - 用户表 `users`：120 条
  - 医生排班表 `doctor_schedules`：3600 条
  - 预约表 `appointments`：8400 条

当前 mock 生成策略：

- 15 个科室 × 每科 4 位医生 × 未来 30 天 × 上午/下午双时段自动生成排班
- 自动混入部分 `STOPPED` 停诊排班（含 `stop_reason`）
- 预约数据按排班剩余号源规则自动生成，便于预约/取消/查询链路压测

可选验证：

```bash
cd py-backend
sqlite3 data/zoe.db 'select id,patient_name,department,appointment_time from appointments order by id;'
sqlite3 data/zoe.db 'select id,name,id_card from users order by id;'
sqlite3 data/zoe.db 'select id,doctor_name,department,schedule_date,time_of_day,available_slots from doctor_schedules order by id;'
```

## 接口

认证接口（简单注册登录）：

- `POST /auth/register` 入参：`{ "username": "alice", "password": "123456" }`
- `POST /auth/login` 入参：`{ "username": "alice", "password": "123456" }`

- `POST /zoe/chat`（流式文本）
  - 入参：`{ "userId": 1, "memoryId": "123", "message": "你好" }`
- `POST /zoe/memory/compress`
  - 入参：`{ "userId": 1, "memoryId": "123" }`
- `GET /zoe/sessions?userId=1`
  - 返回该用户下的历史会话列表（从 MongoDB 会话集合读取）
- `GET /zoe/sessions/{memoryId}?userId=1`
  - 返回指定会话的历史消息（从 MongoDB 会话集合读取）
- `GET /appointments`
- `POST /appointments`
- `PUT /appointments/{id}`
- `DELETE /appointments/{id}`

排班管理接口：

- `GET /schedules?department=神经内科&schedule_date=2026-03-18`
- `POST /schedules` 新增排班
- `PUT /schedules/{id}/stop` 停诊（置为 `STOPPED` 且可用号源清零）
- `PUT /schedules/{id}/slots` 调整号源（可恢复为 `ACTIVE`）

## Function Calling 工具

Agent 可调用以下工具（由后端执行）：

- `recommend_department(symptom)`
- `check_registration_slots(department, appointment_date)`
- `book_appointment(patient_name, id_card, department, appointment_date, time_of_day, doctor)`
- `cancel_appointment(patient_name, id_card, department, appointment_date, time_of_day, doctor)`
- `query_appointment_records(patient_name, id_card)`

## 记忆与会话持久化说明

当前实现采用“业务数据 SQLite + 记忆 MongoDB + 日志 JSONL”混合持久化：

- 业务数据库：`py-backend/data/zoe.db`（SQLite）
- 分层记忆：MongoDB 集合（默认 `zoe.layered_memory`）
- 用户结构化长期记忆：MongoDB 集合（默认 `zoe.user_profiles`，按 `user_id` 聚合）
- 轨迹缓冲区：MongoDB 集合（默认 `zoe.trajectory_buffer`，In-Context RL 用）
- 会话信息：MongoDB 集合（默认 `zoe.conversation_sessions`）
- 会话日志：`py-backend/data/logs/conversation_*.jsonl`（保留，便于排障和人工查看）

说明：

- 函数调用工作记忆保存在会话文档字段 `tool_working_memory`（dict），包含：`intent`、`required_fields`、`collected_fields`、`missing_fields`、`status`、`last_tool_calls`
- 会话短期记忆继续采用滑动窗口（`WORKING_MEMORY_WINDOW`）
- 自动压缩按字符阈值触发（`AUTO_COMPRESS_TRIGGER_CHARS`，默认 2200）；即使轮次较多，只要窗口内字符数未达到阈值也不会自动压缩
- 触发压缩后会写入 `short_term_summary`、`session_facts`，并同步更新 `user_profiles`（用户结构化长期记忆）
- 若需立即生成长期画像，可手动调用 `POST /zoe/memory/compress`
- 长期记忆采用轻路由：仅在问题命中“历史/继续/复诊/过敏/慢病”等记忆意图时触发 BM25 检索

会话隔离策略：后端会把 `userId + memoryId` 组合成作用域 ID（例如 `user_1_mem_123`），不同账号的会话与日志天然隔离。

## In-Context RL（上下文强化学习）

系统内置了一套不依赖模型权重更新的 In-Context RL 闭环，通过在 prompt 中注入历史经验来持续改进 Agent 行为。

### 核心组件

| 组件 | 文件 | 说明 |
|------|------|------|
| TrajectoryStore | `app/memory/trajectory_store.py` | 轨迹存储与检索 |
| Reflection Prompt | `prompts/reflection_prompt.txt` | 自评提示词 |
| Strategy Notes | `layered_memory.strategy_notes` 字段 | 策略笔记（会话级） |

### 工作机制

#### 1. Reward-Annotated Experience Replay（轨迹标注与回放）

每轮工具调用后自动标注：

- **Outcome 分类**：`success` / `failure` / `partial` / `retry_success` / `no_tool`
- **Reward 计算**：基于 outcome + 工具调用效率，范围 0.0~1.0
- **Per-step Rewards**：每个工具调用独立打分
- **存储**：写入 MongoDB `trajectory_buffer` 集合

Reward 规则：

| Outcome | Base Reward | 说明 |
|---------|-------------|------|
| success | 1.0 | 工具调用成功 |
| retry_success | 0.6 | 失败后重试成功 |
| partial | 0.5 | 部分成功 |
| no_tool | 0.5 | 纯问答无工具调用 |
| failure | 0.0 | 工具调用失败 |

额外效率奖励：`min(0.2, 0.2 / tool_count)`，工具调用次数越少奖励越高。

下次遇到类似问题时，系统从 `trajectory_buffer` 中 BM25 检索高 reward 轨迹，注入 prompt 的 `[历史成功轨迹参考]` 区块。

#### 2. Self-Reflection Node（策略反思节点）

`save_memory` 之后自动执行（仅在有工具调用时触发）：

1. 调用 LLM 对本轮交互自评
2. 输出 `efficiency_score`（1-5）、`strategy_notes`（策略经验）、`improvement`（改进建议）
3. 策略笔记写入 `layered_memory.strategy_notes`，下次通过 `render_context()` 注入
4. 效率评分和改进建议附加到对应轨迹记录

#### 3. LangGraph 流程

```
load_memory → retrieve_trajectories → retrieve_docs → generate_answer → save_memory → reflect → END
```

模型每轮看到的 `memory_context` 包含 7 个区块：

1. `[短期摘要]`
2. `[会话稳定事实]`
3. `[策略反思笔记]`
4. `[函数调用工作记忆]`
5. `[长期记忆检索结果]`
6. `[用户结构化长期记忆]`
7. `[工作记忆]`

系统提示词 `chat_system_prompt.txt` 中另有 `[历史成功轨迹参考]` 注入区块。

## 常见排查

- 现象：已经聊了很多轮，但 `layered_memory.last_compressed_at` 仍为空
  - 原因：自动压缩基于“窗口内字符数”而不是“轮次”触发
  - 处理：
    - 调低 `.env` 中 `AUTO_COMPRESS_TRIGGER_CHARS`（例如改为 1200）
    - 或手动调用 `POST /zoe/memory/compress`

- 现象：`user_profiles` 里没有该用户画像
  - 原因：用户画像在压缩阶段同步提取，未触发压缩前可能为空
  - 处理：手动压缩一次后再查看 `zoe.user_profiles`
