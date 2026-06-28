import os
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", frozen=True
    )

    TELEGRAM_BOT_TOKEN: SecretStr = Field(min_length=1)
    OPENAI_API_KEY: SecretStr = Field(default=SecretStr(""))
    OPENAI_BASE_URL: SecretStr = Field(default=SecretStr(""))
    MODEL_ID: str

    DATABASE_PATH: str
    AGENT_SESSION_DB_PATH: str

    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    MAX_FILE_SIZE_MB: int = 10

    @computed_field
    @property
    def MAX_FILE_SIZE_BYTES(self) -> int:
        return self.MAX_FILE_SIZE_MB * 1024 * 1024

    VALID_CATEGORIES: list[str] = [
        "makanan",
        "transport",
        "tagihan",
        "kesehatan",
        "belanja",
        "hiburan",
        "tabungan",
        "pemasukan",
        "lainnya",
    ]

    CATEGORY_EMOJI: dict[str, str] = {
        "makanan": "🍽️",
        "transport": "🚗",
        "tagihan": "📋",
        "kesehatan": "💊",
        "belanja": "🛒",
        "hiburan": "🎮",
        "tabungan": "💰",
        "pemasukan": "💵",
        "lainnya": "📌",
    }

    SUPPORTED_IMAGE_TYPES: set[str] = {"image/jpeg", "image/png", "image/webp"}
    SUPPORTED_DOC_TYPES: set[str] = {"application/pdf"}

    @property
    def telegram_api_key(self):
        return self.TELEGRAM_BOT_TOKEN.get_secret_value()

    @property
    def openai_api_key(self) -> str:
        return self.OPENAI_API_KEY.get_secret_value()

    @property
    def openai_base_url(self) -> str:
        return self.OPENAI_BASE_URL.get_secret_value()

    @model_validator(mode="after")
    def validate_llm_keys(self) -> "Settings":
        """
        Ensure the SecretStr API Key corresponding to the provider has been filled.
        """
        if not self.TELEGRAM_BOT_TOKEN.get_secret_value():
            raise ValueError("TELEGRAM_BOT_TOKEN is required")

        if not self.OPENAI_API_KEY.get_secret_value():
            raise ValueError("OPENAI_API_KEY is required")

        if not self.OPENAI_BASE_URL.get_secret_value():
            raise ValueError("OPENAI_BASE_URL is required")

        return self

    @model_validator(mode="after")
    def ensure_db_directory(self) -> "Settings":
        """
        Automatically create data folder SQLite if does not already exist
        """
        for path in (self.DATABASE_PATH, self.AGENT_SESSION_DB_PATH):
            db_dir = os.path.dirname(path)
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir, exist_ok=True)

        return self


@lru_cache()
def get_settings() -> Settings:
    """
    Returns the cached settings instance cache after first read
    """
    return Settings()


settings = get_settings()
