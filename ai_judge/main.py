from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

from ai_judge.config import Settings
from ai_judge.phase1.generation import ChatCompletionsGenerator, GenAISettings, Generator
from ai_judge.phase1.operations import Operations
from ai_judge.phase1.routes import router
from ai_judge.phase1.sampling import SamplingService, SamplingSettings
from ai_judge.phase1.settings import Phase1Settings
from ai_judge.storage.database import Database, StorageError, create_database_engine
from ai_judge.storage.tables import SCHEMA_REVISION


class Health(BaseModel):
    status: str


def create_app(
    database: Database | None = None,
    *,
    phase1_settings: Phase1Settings | None = None,
    generator: Generator | None = None,
    genai_settings: GenAISettings | None = None,
    sampling_settings: SamplingSettings | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.database = database or Database(create_database_engine(Settings()))
        app.state.phase1_settings = phase1_settings or Phase1Settings()
        settings = genai_settings or GenAISettings()
        client = httpx.Client(
            follow_redirects=False, trust_env=False, timeout=settings.timeout_seconds
        )
        app.state.generator = generator or ChatCompletionsGenerator(settings, client)
        app.state.sampler = SamplingService(
            Operations(app.state.database),
            sampling_settings or SamplingSettings(),
        )
        try:
            yield
        finally:
            client.close()
            if database is None:
                app.state.database.close()

    app = FastAPI(title="AI Judge", version="0.1.0", lifespan=lifespan)
    app.include_router(router)

    @app.get("/health/live", response_model=Health, tags=["C-1"])
    def live():
        return {"status": "ok"}

    @app.get(
        "/health/ready",
        response_model=Health,
        tags=["C-1"],
        responses={
            503: {"model": Health, "description": "Database unavailable or migration required"},
        },
    )
    def ready():
        try:
            with app.state.database.transaction() as connection:
                revision = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one_or_none()
                if revision != SCHEMA_REVISION:
                    return JSONResponse(status_code=503, content={"status": "unavailable"})
        except StorageError:
            return JSONResponse(status_code=503, content={"status": "unavailable"})
        return {"status": "ready"}

    return app


app = create_app()
