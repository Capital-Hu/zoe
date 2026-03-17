# AGENTS.md

本文件用于规范本仓库内 AI Coding Agent（以及人工协作者）的工作方式，确保改动稳定、可复现、可追踪。

## 1. 项目目标

本项目是一个医疗问答与就医流程助手，当前形态：

- 后端：Python（LangChain + LangGraph + FastAPI）
- 前端：Vue 3 + Element Plus
- 检索：本地混合检索（FAISS 向量 + BM25）
- 记忆：分层记忆（工作记忆、短期摘要、长期记忆）
- 会话日志：本地 JSONL 落盘
- 业务数据库：SQLite

## 2. 关键目录

- py-backend/: Python 后端
- py-backend/app/: 后端核心代码
- py-backend/scripts/: 初始化与运维脚本
- py-backend/prompts/: 外置提示词
- py-backend/data/: 本地数据目录（数据库、向量索引、记忆、日志）
- knowledge/: 本地知识库源文档
- zoe-ui/: Vue 前端

## 3. 本地环境与启动

推荐使用 Conda 环境 zoe（Python 3.11）：

```bash
cd py-backend
conda create -n zoe python=3.11 -y
conda activate zoe
pip install -r requirements.txt
cp .env.example .env
```

知识库预处理（必须先做一次）：

```bash
cd py-backend
conda activate zoe
PYTHONPATH=. python scripts/preprocess_knowledge.py
```

数据库与 mock 数据：

```bash
cd py-backend
conda activate zoe
PYTHONPATH=. python scripts/seed_mock_data.py
```

启动后端：

```bash
cd py-backend
conda activate zoe
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

启动前端：

```bash
cd zoe-ui
npm install
npm run dev
```

## 4. API 与身份隔离约定

### 4.1 简单认证

- POST /auth/register
- POST /auth/login

返回 userId + username。前端应保存登录态，并在聊天请求中传 userId。

### 4.2 会话隔离

聊天和记忆压缩请求必须带：

- userId
- memoryId（字符串）

后端会拼接作用域会话 ID：

- user_{userId}_mem_{memoryId}

用于隔离不同账号的会话记忆与日志。

## 5. 数据持久化说明

### 5.1 业务数据（SQLite）

文件：

- py-backend/data/zoe.db

核心表：

- accounts（账号）
- users（患者）
- doctor_schedules（排班）
- appointments（预约）

### 5.2 记忆与日志

- 分层记忆：py-backend/data/memory/*.json
- 会话日志：py-backend/data/logs/conversation_*.jsonl

每轮聊天日志至少包含：question、answer、memory_context、retrieved_context、tool_trace。

## 6. Agent 开发规则

1. 优先最小改动：仅修改与需求相关文件。
2. 提示词统一外置：禁止在业务代码中硬编码长 Prompt。
3. 涉及就医流程必须优先工具调用（function calling），不要编造预约结果。
4. 先查后改：变更前先阅读相关文件与现状。
5. 保持接口兼容：前端已依赖的路径和字段尽量不破坏。
6. 更新文档：新增能力后同步更新 py-backend/README.md。
7. 关键变更后必须做至少一次 smoke test。

## 7. 排班与预约业务约束

1. 停诊规则：排班 status=STOPPED 时不可预约。
2. 号源规则：available_slots 不能大于 total_slots，且不能小于 0。
3. 取消规则：取消预约时应回补排班可用号源。
4. 预约规则：预约必须校验用户信息与排班可用性。

## 8. 常见任务流程

### 8.1 新增后端能力

1. 在 app/schemas.py 定义请求模型
2. 在 app/main.py 增加路由
3. 若涉及 Agent，更新 app/agent_tools.py 或 graph 流程
4. 更新 README
5. 运行 smoke test

### 8.2 新增 Prompt

1. 在 py-backend/prompts/ 新建模板
2. 用 app/prompt_loader.py 渲染
3. 在调用处注入必要变量
4. 更新 README（说明用途）

### 8.3 检索更新

1. 更新 knowledge/ 文档
2. 重新执行 preprocess_knowledge.py
3. 确认 py-backend/data/vector_store/ 产物已刷新

## 9. 不建议事项

- 不要在代码中写死本机绝对路径。
- 不要把明文 API Key 提交到仓库。
- 不要跳过排班状态直接写预约。
- 不要在未登录状态下提交聊天请求。

## 10. 可选演进路线

- 引入 Token/JWT 鉴权替代仅 userId 校验
- 增加历史会话列表接口
- 增量知识库预处理（仅更新变更文档）
- 需要多实例共享时再迁移 MongoDB
