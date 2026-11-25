"""Response schemas for clients and generated OpenAPI documentation."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from ai_judge.contracts import AttackData


class OperationFailure(BaseModel):
    error: str
    job_id: UUID | None = None
    status: Literal["failed", "interrupted"] | None = None
    elapsed_ms: int | None = None
    details: list[dict] = Field(default_factory=list)


class RequestFailure(BaseModel):
    detail: list[dict]


class Success(BaseModel):
    job_id: UUID
    status: Literal["succeeded"]
    elapsed_ms: int


class ImportResult(Success):
    imported: int
    ids: list[UUID]
    duplicate_policy: Literal["preserve"]


class GenerationResult(Success):
    id: UUID
    data: AttackData
    generation: dict


class SampleItem(BaseModel):
    id: UUID
    data: AttackData


class SamplingResult(Success):
    samples: list[SampleItem]
    sampling: dict


class JobRecord(BaseModel):
    id: UUID
    kind: Literal["attack_import", "template_import", "generation", "sampling"]
    status: Literal["running", "succeeded", "failed", "interrupted"]
    processed: int
    total: int | None
    result: dict | None
    created_at: datetime
    finished_at: datetime | None
    expires_at: datetime


def error_responses(*codes: int) -> dict:
    return {
        code: {"model": OperationFailure | RequestFailure if code == 422 else OperationFailure}
        for code in codes
    }
