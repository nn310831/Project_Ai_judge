import secrets
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from ai_judge.phase2.configuration import ConfigurationService
from ai_judge.phase2.contracts import TargetConfig, TargetError
from ai_judge.phase2.loading import LoadingService, LoadRequest

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
