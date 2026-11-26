import secrets
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from ai_judge.phase2.configuration import ConfigurationService
from ai_judge.phase2.contracts import TargetConfig, TargetError
from ai_judge.phase2.loading import LoadingService, LoadRequest
from ai_judge.phase2.records import RunService, TestRequest

bearer = HTTPBearer(auto_error=False)


def authorize(request: Request, credential: HTTPAuthorizationCredentials | None = Depends(bearer)):
    token = request.app.state.target_settings.api_token
    if token is None or not token.get_secret_value():
        raise TargetError("target_api_not_configured", 503)
    if credential is None or not secrets.compare_digest(
        credential.credentials,
        token.get_secret_value(),
    ):
        raise TargetError("unauthorized", 401)


router = APIRouter(
    prefix="/api/v1/target-models", tags=["Block 2"], dependencies=[Depends(authorize)]
)


class ConfigurationResult(BaseModel):
    model_config_id: UUID
    configuration: TargetConfig


@router.post("/config/ollama", status_code=201, response_model=ConfigurationResult)
def create_config(body: TargetConfig, request: Request):
    service = ConfigurationService(request.app.state.database, request.app.state.target_settings)
    return {"model_config_id": service.create(body), "configuration": body}


@router.get("/config/ollama/{model_config_id}", response_model=ConfigurationResult)
def get_config(model_config_id: UUID, request: Request):
    service = ConfigurationService(request.app.state.database, request.app.state.target_settings)
    return {"model_config_id": model_config_id, "configuration": service.get(model_config_id)}


class LoadResult(BaseModel):
    load_id: UUID
    model_config_id: UUID
    sampling_job_id: UUID
    case_count: int


@router.post("/load/ollama", status_code=201, response_model=LoadResult)
def load_ollama(body: LoadRequest, request: Request):
    service = LoadingService(
        request.app.state.database,
        request.app.state.target_settings,
        request.app.state.target_registry,
    )
    identifier = service.load_job(body)
    return {
        "load_id": identifier,
        "model_config_id": body.model_config_id,
        "sampling_job_id": body.sampling_job_id,
        "case_count": len(service.get(identifier).snapshot.samples),
    }


def run_service(request: Request) -> RunService:
    return RunService(
        request.app.state.database,
        request.app.state.target_settings,
        request.app.state.target_registry,
    )


class AcceptedRun(BaseModel):
    run_id: UUID
    status: Literal["queued"]
    status_url: str


@router.post("/test/ollama", status_code=202, response_model=AcceptedRun)
def start_target_test(
    body: TestRequest, request: Request, x_job_id: UUID | None = Header(default=None)
):
    run_id = run_service(request).submit(body, x_job_id)
    return {
        "run_id": run_id,
        "status": "queued",
        "status_url": f"/api/v1/target-models/test/ollama/{run_id}",
    }


class RunStatus(BaseModel):
    id: UUID
    load_id: UUID
    status: Literal["queued", "running", "succeeded", "failed", "interrupted", "partial"]
    total_cases: int
    completed_cases: int
    failed_cases: int
    current_case_id: UUID | None
    current_round: int | None
    error: str | None
    created_at: datetime
    finished_at: datetime | None
    lease_expires_at: datetime | None
    execution: dict


class RecordPage(BaseModel):
    items: list[dict]
    limit: int
    offset: int


@router.get("/test/ollama/{run_id}", response_model=RunStatus)
def run_status(run_id: UUID, request: Request):
    return run_service(request).status(run_id)


@router.get("/test/ollama/{run_id}/cases", response_model=RecordPage)
def case_records(
    run_id: UUID,
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return {
        "items": run_service(request).cases(run_id, limit, offset),
        "limit": limit,
        "offset": offset,
    }


@router.get("/test/ollama/{run_id}/cases/{case_id}/rounds", response_model=RecordPage)
def round_records(
    run_id: UUID,
    case_id: UUID,
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return {
        "items": run_service(request).rounds(run_id, case_id, limit, offset),
        "limit": limit,
        "offset": offset,
    }
