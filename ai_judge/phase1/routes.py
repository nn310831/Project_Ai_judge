from uuid import UUID

from fastapi import APIRouter, Header, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ai_judge.phase1.api_models import (
    GenerationResult,
    ImportResult,
    JobRecord,
    SamplingResult,
    error_responses,
)
from ai_judge.phase1.generation import GenerationRequest, GenerationService
from ai_judge.phase1.importers import Importer
from ai_judge.phase1.operations import Operations
from ai_judge.phase1.sampling import SamplingRequest
from ai_judge.storage.database import StorageError

router = APIRouter(prefix="/api/v1", tags=["Block 1"])


async def read_body(request: Request, media_type: str) -> bytes | JSONResponse:
    if request.headers.get("content-type", "").split(";")[0].strip() != media_type:
        return JSONResponse(status_code=415, content={"error": "unsupported_media_type"})
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > request.app.state.phase1_settings.max_body_bytes:
            return JSONResponse(status_code=413, content={"error": "body_too_large"})
    return bytes(raw)


@router.post(
    "/attacks/import",
    status_code=201,
    response_model=ImportResult,
    responses=error_responses(409, 413, 415, 422, 503),
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/x-ndjson": {"schema": {"type": "string"}}},
        }
    },
)
async def import_attacks(request: Request, x_job_id: UUID | None = Header(default=None)):
    raw = await read_body(request, "application/x-ndjson")
    if isinstance(raw, JSONResponse):
        return raw
    importer = Importer(Operations(request.app.state.database), request.app.state.phase1_settings)
    status, result = await run_in_threadpool(importer.attacks, raw, x_job_id)
    return JSONResponse(status_code=status, content=result)


@router.get(
    "/attack-jobs/{job_id}", response_model=JobRecord, responses=error_responses(404, 422, 503)
)
def get_job(job_id: UUID, request: Request):
    try:
        job = Operations(request.app.state.database).get(job_id)
    except StorageError:
        return JSONResponse(status_code=503, content={"error": "storage_unavailable"})
    if job is None:
        return JSONResponse(status_code=404, content={"error": "job_not_found"})
    return JSONResponse(content=jsonable_encoder(job))


@router.post(
    "/attack-templates/import",
    status_code=201,
    response_model=ImportResult,
    responses=error_responses(409, 413, 415, 422, 503),
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {"schema": {"oneOf": [{"type": "object"}, {"type": "array"}]}}
            },
        }
    },
)
async def import_templates(request: Request, x_job_id: UUID | None = Header(default=None)):
    raw = await read_body(request, "application/json")
    if isinstance(raw, JSONResponse):
        return raw
    importer = Importer(Operations(request.app.state.database), request.app.state.phase1_settings)
    status, result = await run_in_threadpool(importer.templates, raw, x_job_id)
    return JSONResponse(status_code=status, content=result)


@router.post(
    "/attacks/generate",
    status_code=201,
    response_model=GenerationResult,
    responses=error_responses(404, 409, 422, 429, 502, 503, 504),
)
def generate_attack(
    body: GenerationRequest,
    request: Request,
    x_job_id: UUID | None = Header(default=None),
):
    service = GenerationService(Operations(request.app.state.database), request.app.state.generator)
    status, result = service.generate(body, x_job_id)
    return JSONResponse(status_code=status, content=result)


@router.post(
    "/attacks/sample",
    status_code=201,
    response_model=SamplingResult,
    responses=error_responses(409, 422, 429, 503),
)
def sample_attacks(
    body: SamplingRequest,
    request: Request,
    x_job_id: UUID | None = Header(default=None),
):
    status, result = request.app.state.sampler.sample(body, x_job_id)
    return JSONResponse(status_code=status, content=result)
