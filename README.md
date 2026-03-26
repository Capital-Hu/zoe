# 基于langchain4j的简单java大模型应用部署及RAG项目，医疗问答、挂号大模型
# zoe大模型（医疗版）
 
尚硅谷-Zoe

## 前置知识

- Java基础
- Maven
- MySQL
- SSM
- SpringBoot

## 实现b站项目小智医疗：
   https://www.bilibili.com/video/BV1cpLTz1EVp/?spm_id_from=333.337.search-card.all.click&vd_source=65e57e353e5dcc7156a1676a51972f12

## Python后端（新）

已新增 `py-backend/`，使用 LangChain + LangGraph 替代原 Java LangChain4j 对话后端。

- 本地知识库目录：项目根目录 `knowledge/`
- 检索方式：FAISS 向量检索 + BM25 混合检索
- 记忆架构：工作记忆 + 短期摘要 + 长期记忆
- 记忆压缩接口：`POST /zoe/memory/compress`
- 代码结构：按 `api / agents / memory / db / retrieval / llm / schemas / core` 分层

启动方式见：`py-backend/README.md`

   
