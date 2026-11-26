from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Phase1Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AI_JUDGE_PHASE1_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )
    max_body_bytes: int = Field(default=2_000_000, ge=1, le=20_000_000)
    max_import_records: int = Field(default=1000, ge=1, le=10000)
