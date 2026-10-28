from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """API settings, read from API_* environment variables or an api/.env file."""

    model_config = SettingsConfigDict(
        env_prefix="API_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Direct Postgres connection used for local development, e.g.
    # postgresql+psycopg://web_serving_tables_reader:<password>@<aurora-host>:5432/<db>
    database_url: str = ""
    # Seconds psycopg waits to connect; a paused Aurora cluster needs ~10-15 s to resume.
    db_connect_timeout: int = 30


def get_settings() -> Settings:
    return Settings()
