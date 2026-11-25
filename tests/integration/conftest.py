import os
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

from ai_judge.config import Settings
from ai_judge.storage.database import Database, create_database_engine


@pytest.fixture
def postgres():
    url = os.environ.get("AI_JUDGE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set AI_JUDGE_TEST_DATABASE_URL to an isolated PostgreSQL *_test database")
    if not (make_url(url).database or "").endswith("_test"):
        pytest.fail("Integration database name must end in _test")
    engine = create_database_engine(Settings(_env_file=None, database_url=url))
    schema = "ai_judge_test_" + uuid4().hex
    with engine.begin() as connection:
        connection.execute(sa.schema.CreateSchema(schema))

    @sa.event.listens_for(engine, "connect")
    def search_path(connection, _):
        # Only locally generated hex identifiers enter this statement.
        with connection.cursor() as cursor:
            cursor.execute(f'SET search_path TO "{schema}"')
        connection.commit()

    engine.dispose()
    config = Config("alembic.ini")
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            command.upgrade(config, "head")  # Re-running must be safe.
            command.check(config)  # ORM/Core metadata and migration must agree.
        yield Database(engine), config
    finally:
        with engine.begin() as connection:
            connection.execute(sa.schema.DropSchema(schema, cascade=True))
        engine.dispose()
