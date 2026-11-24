from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

from ai_judge.config import Settings
from ai_judge.storage.database import Database, StorageError, create_database_engine


class Health(BaseModel):
    status: str


def create_app(database: Database | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.database = database or Database(create_database_engine(Settings()))
        try:
            yield
        finally:
            if database is None:
                app.state.database.close()

    app = FastAPI(title="AI Judge", version="0.1.0", lifespan=lifespan)

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
                if revision != "0001_common_storage":
                    return JSONResponse(status_code=503, content={"status": "unavailable"})
        except StorageError:
            return JSONResponse(status_code=503, content={"status": "unavailable"})
        return {"status": "ready"}

    return app


app = create_app()
