from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from app.config import settings


class ModelBundle:
    def __init__(self):
        self.llm = self._build_chat_model()
        self.embedding = self._build_embedding_model()

    def _build_chat_model(self):
        if settings.model_provider == "ollama":
            return ChatOllama(
                model=settings.ollama_chat_model,
                base_url=settings.ollama_base_url,
                temperature=0.3,
            )
        return ChatOpenAI(
            model=settings.chat_model,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            temperature=0.3,
            streaming=False,
        )

    def _build_embedding_model(self):
        if settings.model_provider == "ollama":
            return OllamaEmbeddings(
                model=settings.ollama_embed_model,
                base_url=settings.ollama_base_url,
            )
        return OpenAIEmbeddings(
            model=settings.embedding_model,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )
