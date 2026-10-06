from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    s3_bucket: str = ""
    aws_region: str = "ca-central-1"
    athena_workgroup: str = "fb-marketplace-greatdeals"
    apify_api_token: str = ""
    gemini_api_key: str = ""


settings = Settings()
