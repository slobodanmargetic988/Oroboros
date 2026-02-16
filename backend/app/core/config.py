from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Ouroboros API"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/builder_control"
    slot_ids_csv: str = "preview-1,preview-2,preview-3"
    slot_lease_ttl_seconds: int = 1800


@lru_cache
def get_settings() -> Settings:
    return Settings()
