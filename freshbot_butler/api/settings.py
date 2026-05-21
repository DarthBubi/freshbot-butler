from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = "sqlite+aiosqlite:///./freshbot-butler.sqlite3"
    host: str = "0.0.0.0"
    port: int = 8000
    session_token_ttl_hours: int = 168
    transcription_provider: str = "openai"
    transcription_openai_api_key: str | None = None
    transcription_openai_base_url: str = "https://api.openai.com/v1"
    transcription_openai_model: str = "whisper-1"

    model_config = SettingsConfigDict(env_prefix="FRESHBOT_", extra="ignore")
