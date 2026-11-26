from typing import Annotated, Literal, Self
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from ai_judge.contracts import Contract, Text

Identifier = Annotated[UUID, Field(strict=False)]


class TargetError(Exception):
    def __init__(self, code: str, status: int = 422):
        super().__init__(code)
        self.code, self.status = code, status


class OllamaParameters(Contract):
    temperature: float = Field(default=0.7, ge=0, le=2)
    top_p: float = Field(default=0.9, gt=0, le=1)
    top_k: int = Field(default=40, ge=1, le=200)
    num_predict: int = Field(default=2048, ge=1, le=8192)
    num_ctx: int = Field(default=8192, ge=512, le=131072)
    seed: int = Field(default=0, ge=-1, le=2**31 - 1)


class TargetConfig(Contract):
    provider: Literal["ollama"] = "ollama"
    base_url: Text
    model: Text
    model_version: Text | None = None
    parameters: OllamaParameters = Field(default_factory=OllamaParameters)
    timeout_seconds: float = Field(default=30, ge=1, le=60)
    context_max_characters: int = Field(default=24000, ge=512, le=256000)
    window_turns: int = Field(default=6, ge=1, le=100)
    max_response_bytes: int = Field(default=1_000_000, ge=100, le=5_000_000)

    @model_validator(mode="after")
    def fits_context(self) -> Self:
        if self.parameters.num_predict >= self.parameters.num_ctx:
            raise ValueError("num_predict must be smaller than num_ctx")
        return self

    @field_validator("base_url")
    @classmethod
    def clean_base_url(cls, value: str) -> str:
        url = urlsplit(value)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or any(c.isspace() for c in value)
        ):
            raise ValueError("Use a plain HTTP(S) base URL without credentials or query")
        return value.rstrip("/")
