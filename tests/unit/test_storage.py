from uuid import uuid4

import pytest
import sqlalchemy as sa

from ai_judge.storage.database import StorageError
from ai_judge.storage.repository import ReferenceError, Repository
from ai_judge.storage.tables import attack_templates, attacks


def test_roundtrip_and_relation(database, attack, template):
    with database.transaction() as connection:
        repo = Repository(connection)
        tid = repo.add_template(template)
        ids = repo.add_attacks([attack, attack], source_template_id=tid)
    with database.transaction() as connection:
        repo = Repository(connection)
        assert repo.get_template(tid).data == template
        assert repo.get_attack(ids[0]).data == attack
        assert repo.get_attack(ids[0]).source_template_id == tid
        assert ids[0] != ids[1]  # No implicit deduplication policy.
        assert repo.get_attack(uuid4()) is None
        assert repo.get_template(uuid4()) is None
        assert len(repo.list_attacks(subcategory="synthetic", limit=1, offset=1)) == 1
        assert repo.list_attacks(subcategory="'; DROP TABLE attacks;--") == []
        assert repo.add_attacks([]) == []


def test_application_failure_rolls_back_entire_transaction(database, attack, template):
    with pytest.raises(RuntimeError):
        with database.transaction() as connection:
            repo = Repository(connection)
            tid = repo.add_template(template)
            aid = repo.add_attacks([attack], source_template_id=tid)[0]
            raise RuntimeError("abort")
    with database.transaction() as connection:
        assert Repository(connection).get_template(tid) is None
        assert Repository(connection).get_attack(aid) is None


def test_sql_failure_rolls_back_and_redacts(database, attack):
    with pytest.raises(StorageError, match="^Database operation failed$"):
        with database.transaction() as connection:
            aid = Repository(connection).add_attacks([attack])[0]
            connection.execute(
                attacks.insert().values(
                    id=aid,
                    subcategory="sensitive payload",
                    payload=attack.model_dump(),
                )
            )
    with database.transaction() as connection:
        assert Repository(connection).get_attack(aid) is None


def test_missing_or_mismatched_reference(database, attack, template):
    with database.transaction() as connection:
        repo = Repository(connection)
        with pytest.raises(ReferenceError):
            repo.add_attacks([attack], source_template_id=uuid4())
        tid = repo.add_template(template)
        attack.subcategory = "different"
        with pytest.raises(ReferenceError):
            repo.add_attacks([attack], source_template_id=tid)
        assert repo.list_attacks() == []


def test_foreign_key_restricts_deletion(database, attack, template):
    with database.transaction() as connection:
        repo = Repository(connection)
        tid = repo.add_template(template)
        repo.add_attacks([attack], source_template_id=tid)
    with pytest.raises(StorageError):
        with database.transaction() as connection:
            connection.execute(sa.delete(attack_templates).where(attack_templates.c.id == tid))


@pytest.mark.parametrize("limit,offset", [(0, 0), (1001, 0), (1, -1)])
def test_pagination_bounds(database, limit, offset):
    with database.transaction() as connection:
        with pytest.raises(ValueError):
            Repository(connection).list_attacks(limit=limit, offset=offset)
