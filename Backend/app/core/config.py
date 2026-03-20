from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    GEMINI_API_KEY: str | None = None
    GOOGLE_API_KEY: str | None = None
    GEMINI_MODEL: str = "gemini-2.5-flash"

    DATABASE_URL: str = "sqlite+aiosqlite:///./app.db"

    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str | None = None
    QDRANT_COLLECTION: str = "nckh_docs"
    COLLECTION_NAME: str = "nckh_docs"

    EMBEDDING_VECTOR_SIZE: int = 1024

    CHUNK_SIZE: int = 800
    CHUNK_OVERLAP: int = 100
    OVERLAP: int = 100
    MAX_CHUNK_TOKENS: int = 800
    OVERLAP_TOKENS: int = 100

    CUDA_VISIBLE_DEVICES: str = ""
    DEVICE: str = "cpu"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def EFFECTIVE_GEMINI_API_KEY(self) -> str:
        key = self.GOOGLE_API_KEY or self.GEMINI_API_KEY
        if not key:
            raise ValueError("Cần GOOGLE_API_KEY hoặc GEMINI_API_KEY")
        return key

    @field_validator("GEMINI_MODEL")
    @classmethod
    def validate_model(cls, v: str) -> str:
        return v.strip()
    TEMPERATURE: float = 0.7
    MAX_OUTPUT_TOKENS: int = 4096


settings = Settings()