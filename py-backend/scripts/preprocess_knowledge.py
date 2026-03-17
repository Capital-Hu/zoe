from __future__ import annotations

from datetime import datetime

from app.config import settings
from app.models import build_embedding_model
from app.retriever import HybridRetriever


def main() -> None:
    started = datetime.now()
    print("[preprocess] start:", started.isoformat())
    print("[preprocess] knowledge dir:", settings.knowledge_dir)
    print("[preprocess] vector dir:", settings.vector_dir)

    embedding_model = build_embedding_model()
    retriever = HybridRetriever(embedding_model)

    elapsed = datetime.now() - started
    print("[preprocess] done")
    print("[preprocess] corpus chunks:", retriever.corpus_size())
    print("[preprocess] faiss index:", settings.vector_dir / "index.faiss")
    print("[preprocess] bm25 meta:", settings.vector_dir / "bm25_meta.json")
    print("[preprocess] bm25 cache:", settings.vector_dir / "bm25.pkl")
    print("[preprocess] elapsed:", elapsed)


if __name__ == "__main__":
    main()
