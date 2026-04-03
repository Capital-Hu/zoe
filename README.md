# Zoe 医疗问答与就医助手

这是一个面向医疗咨询与就医流程场景的智能助手项目，支持医疗问答、排班查询、预约挂号等能力。

当前仓库采用前后端分离架构，并包含两套实现：

- Python 后端（主线）：基于 FastAPI + LangChain + LangGraph
- Java 模块（保留）：基于 Spring Boot + LangChain4j

## 核心能力

- 医疗知识问答（基于本地知识库 RAG）
- 混合检索（FAISS 向量检索 + BM25 关键词检索）
- 分层会话记忆（工作记忆、短期摘要、长期记忆）
- 就医流程工具调用（如排班、预约、取消）
- 会话日志与记忆持久化（MongoDB + 本地 JSONL）

## 项目结构

- `py-backend/`：Python 后端主服务
- `zoe-ui/`：Vue 3 前端
- `knowledge/`：本地知识库文档
- `docs/`：项目文档（如记忆架构说明）
- `src/`：Java 代码（历史/扩展模块）

## Python 后端说明（推荐使用）

Python 后端位于 `py-backend/`，采用分层结构：

- `app/api`：FastAPI 路由
- `app/agents`：LangGraph 编排与工具调用
- `app/retrieval`：混合检索
- `app/memory`：记忆管理与会话日志
- `app/db`：数据库模型与访问
- `app/llm`：模型装配
- `app/schemas`：请求/响应模型
- `app/core`：配置与安全

关键接口示例：

- `POST /auth/register`
- `POST /auth/login`
- `POST /zoe/chat`
- `POST /zoe/memory/compress`

## 快速开始

### 1. 启动 Python 后端

```bash
cd py-backend
pip install -r requirements.txt
cp .env.example .env
```

首次使用请先执行知识库预处理：

```bash
cd py-backend
PYTHONPATH=. python scripts/preprocess_knowledge.py
```

初始化数据库与示例数据：

```bash
cd py-backend
PYTHONPATH=. python scripts/seed_mock_data.py
```

启动服务：

```bash
cd py-backend
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

### 2. 启动前端

```bash
cd zoe-ui
npm install
npm run dev
```

## 数据与存储

- 业务库：SQLite（默认 `py-backend/data/zoe.db`）
- 记忆存储：MongoDB（分层记忆与会话表）
- 会话日志：`py-backend/data/logs/conversation_*.jsonl`

## 开发建议

- 修改 Prompt 请放在 `py-backend/prompts/`，避免在业务代码硬编码长提示词
- 涉及挂号流程时优先走工具调用，不直接编造业务结果
- 变更后建议至少执行一次 smoke test

## 更多说明

后端详细说明请查看 `py-backend/README.md`。

 

