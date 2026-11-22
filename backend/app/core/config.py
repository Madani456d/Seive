from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    mock_mode: bool = True
    mock_treg: bool = True
    database_url: str = ""
    gemini_api_key: str = ""
    treg_api_key: str = ""
    treg_token: str = ""
    treg_base_url: str = "https://api.treg.to/v1"
    max_run_budget_usd: float = 0.25

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
