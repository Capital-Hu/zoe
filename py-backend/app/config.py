from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parents[1] / ".env"),
        env_file_encoding="utf-8",
    )

    host: str = Field(default="0.0.0.0", alias="HOST")
    port: int = Field(default=8080, alias="PORT")

    model_provider: str = Field(default="openai_compatible", alias="MODEL_PROVIDER")

    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="", alias="OPENAI_BASE_URL")
    chat_model: str = Field(default="deepseek-v3", alias="CHAT_MODEL")
    embedding_model: str = Field(default="text-embedding-v3", alias="EMBEDDING_MODEL")

    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")
    ollama_chat_model: str = Field(default="qwen2.5:7b", alias="OLLAMA_CHAT_MODEL")
    ollama_embed_model: str = Field(default="nomic-embed-text", alias="OLLAMA_EMBED_MODEL")

    top_k: int = Field(default=4, alias="TOP_K")
    min_score: float = Field(default=0.2, alias="MIN_SCORE")
    working_memory_window: int = Field(default=6, alias="WORKING_MEMORY_WINDOW")
    auto_compress_trigger_chars: int = Field(default=2200, alias="AUTO_COMPRESS_TRIGGER_CHARS")
    long_term_memory_top_k: int = Field(default=3, alias="LONG_TERM_MEMORY_TOP_K")
    mongo_uri: str = Field(default="mongodb://localhost:27017", alias="MONGO_URI")
    mongo_db: str = Field(default="zoe", alias="MONGO_DB")
    mongo_memory_collection: str = Field(default="layered_memory", alias="MONGO_MEMORY_COLLECTION")
    mongo_conversation_collection: str = Field(default="conversation_sessions", alias="MONGO_CONVERSATION_COLLECTION")
    mongo_user_profile_collection: str = Field(default="user_profiles", alias="MONGO_USER_PROFILE_COLLECTION")
    mongo_timeout_ms: int = Field(default=3000, alias="MONGO_TIMEOUT_MS")

    @property
    def root_dir(self) -> Path:
        return Path(__file__).resolve().parents[2]

    @property
    def knowledge_dir(self) -> Path:
        return self.root_dir / "knowledge"

    @property
    def data_dir(self) -> Path:
        return self.root_dir / "py-backend" / "data"

    @property
    def vector_dir(self) -> Path:
        return self.data_dir / "vector_store"

    @property
    def prompts_dir(self) -> Path:
        return self.root_dir / "py-backend" / "prompts"

    @property
    def logs_dir(self) -> Path:
        return self.root_dir / "py-backend" / "data" / "logs"


settings = Settings()
