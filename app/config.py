from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _to_sqlalchemy_url(url: str) -> str:
    """Neon gives 'postgresql://...'. SQLAlchemy needs the driver name: 'postgresql+psycopg://...'."""
    if url.startswith("postgresql+psycopg://"):
        return url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    direct_url: str | None = None
    openrouter_api_key: str | None = None
    llm_model: str = "nvidia/nemotron-3-ultra-550b-a55b:free"

    @field_validator("database_url", "direct_url")
    @classmethod
    def fix_driver(cls, v: str | None) -> str | None:
        return _to_sqlalchemy_url(v) if v else v


settings = Settings()