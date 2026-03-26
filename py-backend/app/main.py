from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agents.graph import ZoeGraph
from app.api.dependencies import AppServices
from app.api.router import api_router
from app.db import init_db
from app.llm.bundle import ModelBundle
from app.memory import ConversationLogger, LayeredMemoryStore
from app.retrieval import HybridRetriever

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(title="Zoe Medical Agent (Python)")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)

    @app.on_event("startup")
    def on_startup() -> None:
        init_db()
        conversation_logger = ConversationLogger()
        zoe_graph: ZoeGraph | None = None
        try:
            bundle = ModelBundle()
            retriever = HybridRetriever(bundle.embedding)
            memory_store = LayeredMemoryStore(bundle.llm)
            zoe_graph = ZoeGraph(bundle.llm, retriever, memory_store)
        except Exception as exc:
            logger.warning("Chat agent init skipped: %s", exc)

        app.state.services = AppServices(
            zoe_graph=zoe_graph,
            conversation_logger=conversation_logger,
        )

    return app


app = create_app()
