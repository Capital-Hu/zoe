from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import sys

# Allow running this script directly from py-backend/scripts.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings
from app.models import build_embedding_model
from app.retriever import HybridRetriever


def main() -> None:
    started = datetime.now()
    print("[preprocess] start:", started.isoformat())
    print("[preprocess] knowledge dir:", settings.knowledge_dir)
    print("[preprocess] vector dir:", settings.vector_dir)

    # 强制全量重建：存在旧索引时先删除
    if settings.vector_dir.exists():
        shutil.rmtree(settings.vector_dir)
    settings.vector_dir.mkdir(parents=True, exist_ok=True)

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
