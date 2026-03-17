# Zoe Python Backend (LangChain + LangGraph)

这个目录是新的后端实现，替代原有 Java LangChain4j 对话后端。

## 功能

- LangChain + LangGraph 对话工作流
- 本地知识库检索：读取项目根目录 `knowledge/`
- 混合检索：FAISS 向量检索 + BM25 检索（RRF 融合）
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

## 启动

```bash
cd py-backend
conda activate zoe
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
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

- `POST /zoe/chat`（流式文本）
  - 入参：`{ "memoryId": 123, "message": "你好" }`
- `POST /zoe/memory/compress`
  - 入参：`{ "memoryId": 123 }`
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
