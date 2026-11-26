import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ai_judge.config import Settings
from ai_judge.main import create_app
from ai_judge.storage.database import create_database_engine
from ai_judge.storage.tables import SCHEMA_REVISION


def test_settings_redaction_and_pool():
    settings = Settings(
        _env_file=None, database_url="postgresql+psycopg://test:private-value@localhost/test"
    )
    assert "private-value" not in repr(settings)
    engine = create_database_engine(settings)
    assert engine.pool.size() == 5
    assert engine.hide_parameters
    engine.dispose()


@pytest.mark.parametrize("url", ["sqlite://", "not-a-url", "postgresql+psycopg://localhost"])
def test_settings_reject_non_postgres(url):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=url)


def test_invalid_settings_do_not_print_credentials():
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, database_url="mysql://user:private-value@localhost/test")
    assert "private-value" not in str(error.value)


def test_health_and_openapi(database):
    with TestClient(create_app(database)) as client:
        assert client.get("/health/live").json() == {"status": "ok"}
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json() == {"status": "unavailable"}
        with database.transaction() as connection:
            connection.execute(sa.text("CREATE TABLE alembic_version (version_num TEXT)"))
            connection.execute(sa.text("INSERT INTO alembic_version VALUES ('old')"))
        assert client.get("/health/ready").status_code == 503
        with database.transaction() as connection:
            connection.execute(
                sa.text("UPDATE alembic_version SET version_num = :revision"),
                {"revision": SCHEMA_REVISION},
            )
        assert client.get("/health/ready").json() == {"status": "ready"}
        assert set(client.get("/openapi.json").json()["paths"]) >= {
            "/health/live",
            "/health/ready",
        }
