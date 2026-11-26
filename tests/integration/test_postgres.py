from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command

from ai_judge.storage.database import StorageError
from ai_judge.storage.repository import Repository
from ai_judge.storage.tables import attacks

pytestmark = pytest.mark.integration


def test_postgres_persistence_and_transactions(postgres, attack, template):
    database, _ = postgres
    with database.transaction() as connection:
        repo = Repository(connection)
        tid = repo.add_template(template)
        aid = repo.add_attacks([attack], source_template_id=tid)[0]
        assert (
            connection.execute(
                sa.text(
                    "SELECT data_type FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND table_name = 'attacks' "
                    "AND column_name = 'payload'"
                )
            ).scalar_one()
            == "jsonb"
        )
    database.close()  # Force new physical connections; persisted state must survive.
    with database.transaction() as connection:
        saved = Repository(connection).get_attack(aid)
        assert saved.data == attack
        assert saved.source_template_id == tid
        assert saved.created_at.tzinfo is not None
    with pytest.raises(StorageError):
        with database.transaction() as connection:
            rolled_back = Repository(connection).add_attacks([attack])[0]
            connection.execute(
                attacks.insert().values(
                    id=uuid4(),
                    subcategory="synthetic",
                    payload=attack.model_dump(),
                    source_template_id=uuid4(),
                )
            )
    with database.transaction() as connection:
        assert Repository(connection).get_attack(rolled_back) is None
        assert Repository(connection).get_attack(aid) is not None


def test_postgres_migration_cycle_and_health(postgres):
    from fastapi.testclient import TestClient

    from ai_judge.main import create_app

    database, config = postgres
    with TestClient(create_app(database)) as client:
        assert client.get("/health/ready").status_code == 200
        with database.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "base")
        assert client.get("/health/ready").status_code == 503
        with database.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        assert client.get("/health/ready").status_code == 200


def test_postgres_statement_timeout_and_recovery(postgres):
    database, _ = postgres
    with pytest.raises(StorageError, match="^Database operation failed$"):
        with database.transaction() as connection:
            connection.execute(sa.text("SET LOCAL statement_timeout = 50"))
            connection.execute(sa.text("SELECT pg_sleep(1)"))
    with database.transaction() as connection:
        assert connection.execute(sa.text("SELECT 1")).scalar_one() == 1
