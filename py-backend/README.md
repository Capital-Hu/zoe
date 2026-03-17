# Zoe Python Backend (LangChain + LangGraph)

这个目录是新的后端实现，替代原有 Java LangChain4j 对话后端。

## 功能
  - 入参：`{ "userId": 1, "memoryId": "123", "message": "你好" }`
  - 入参：`{ "userId": 1, "memoryId": "123" }`
- 分层记忆：工作记忆 + 短期摘要 + 长期事实
- 提示词外置：统一放在 `py-backend/prompts/`
- Agent Function Calling：分导诊、查号源、预约、取消预约、记录查询
- 手动压缩记忆接口：`POST /zoe/memory/compress`
- 业务数据表：用户表、医生排班表、预约表（SQLite）

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
  - 用户表 `users`：5 条
  - 医生排班表 `doctor_schedules`：6 条
  - 预约表 `appointments`：5 条

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
  - 返回该用户下的历史会话列表（memoryId、标题、轮次、更新时间）
- `GET /zoe/sessions/{memoryId}?userId=1`
  - 返回指定会话的历史消息，可用于前端点击历史会话后回放
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
- 会话日志：`py-backend/data/logs/conversation_*.jsonl`

会话隔离策略：后端会把 `userId + memoryId` 组合成作用域 ID（例如 `user_1_mem_123`），不同账号的会话与日志天然隔离。
