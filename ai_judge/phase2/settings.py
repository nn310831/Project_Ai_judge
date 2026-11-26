from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class TargetSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AI_JUDGE_TARGET_",
        env_file=".env",
        extra="ignore",
        hide_input_in_errors=True,
    )
    api_token: SecretStr | None = None
    allowed_base_urls: list[str] = Field(default_factory=lambda: ["http://127.0.0.1:11434"])
    mock_enabled: bool = False
    max_cases: int = Field(default=500, ge=1, le=500)
    max_rounds_per_case: int = Field(default=100, ge=1, le=1000)
