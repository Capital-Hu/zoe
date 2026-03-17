from __future__ import annotations

import json
import pickle
from pathlib import Path

import jieba
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from rank_bm25 import BM25Okapi

from app.config import settings


class HybridRetriever:
    def __init__(self, embedding_model):
        self.embedding_model = embedding_model
        settings.vector_dir.mkdir(parents=True, exist_ok=True)
        self.meta_path = settings.vector_dir / "bm25_meta.json"
        self.bm25_path = settings.vector_dir / "bm25.pkl"
        self.vector_store = self._load_or_build_vector_store()
        self.bm25, self.bm25_docs = self._load_or_build_bm25()

    def _scan_knowledge_files(self) -> list[Path]:
        knowledge_dir = settings.knowledge_dir
        files: list[Path] = []
        for ext in ("*.md", "*.txt", "*.pdf"):
            files.extend(knowledge_dir.glob(ext))
        return sorted(files)

    def _load_documents(self) -> list[Document]:
        docs: list[Document] = []
        for file in self._scan_knowledge_files():
            suffix = file.suffix.lower()
            if suffix == ".pdf":
                loaded = PyPDFLoader(str(file)).load()
            else:
                loaded = TextLoader(str(file), encoding="utf-8").load()
            for d in loaded:
                d.metadata["source"] = str(file)
            docs.extend(loaded)
        splitter = RecursiveCharacterTextSplitter(chunk_size=700, chunk_overlap=120)
        return splitter.split_documents(docs)

    def _load_or_build_vector_store(self):
        index_path = settings.vector_dir / "index.faiss"
        if index_path.exists():
            return FAISS.load_local(
                str(settings.vector_dir),
                embeddings=self.embedding_model,
                allow_dangerous_deserialization=True,
            )

        docs = self._load_documents()
        vector_store = FAISS.from_documents(docs, self.embedding_model)
        vector_store.save_local(str(settings.vector_dir))
        return vector_store

    def _load_or_build_bm25(self):
        if self.meta_path.exists() and self.bm25_path.exists():
            meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
            docs = [Document(page_content=item["page_content"], metadata=item["metadata"]) for item in meta]
            with self.bm25_path.open("rb") as f:
                bm25 = pickle.load(f)
            return bm25, docs

        if self.meta_path.exists():
            meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
            docs = [Document(page_content=item["page_content"], metadata=item["metadata"]) for item in meta]
        else:
            docs = self._load_documents()
            serializable = [
                {"page_content": d.page_content, "metadata": d.metadata}
                for d in docs
            ]
            self.meta_path.write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")

        tokenized_corpus = [list(jieba.cut(d.page_content)) for d in docs]
        bm25 = BM25Okapi(tokenized_corpus)
        with self.bm25_path.open("wb") as f:
            pickle.dump(bm25, f)
        return bm25, docs

    def corpus_size(self) -> int:
        return len(self.bm25_docs)

    def _bm25_search(self, query: str, top_k: int) -> list[Document]:
        tokens = list(jieba.cut(query))
        scores = self.bm25.get_scores(tokens)
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
        return [self.bm25_docs[i] for i in top_indices]

    def _vector_search(self, query: str, top_k: int) -> list[Document]:
        pairs = self.vector_store.similarity_search_with_score(query, k=top_k)
        docs: list[Document] = []
        for doc, score in pairs:
            # FAISS 距离越小越相似，这里做一个粗略过滤
            if score <= (1.0 / max(settings.min_score, 0.01)):
                docs.append(doc)
        return docs

    def retrieve(self, query: str, top_k: int | None = None) -> list[Document]:
        k = top_k or settings.top_k
        vector_docs = self._vector_search(query, k)
        bm25_docs = self._bm25_search(query, k)

        # Reciprocal Rank Fusion 融合两个检索结果
        combined: dict[str, tuple[float, Document]] = {}
        for rank, doc in enumerate(vector_docs, start=1):
            key = doc.page_content
            score = 1.0 / (60 + rank)
            prev = combined.get(key)
            combined[key] = ((prev[0] if prev else 0.0) + score, doc)

        for rank, doc in enumerate(bm25_docs, start=1):
            key = doc.page_content
            score = 1.0 / (60 + rank)
            prev = combined.get(key)
            combined[key] = ((prev[0] if prev else 0.0) + score, doc)

        ranked = sorted(combined.values(), key=lambda x: x[0], reverse=True)
        return [doc for _, doc in ranked[:k]]
