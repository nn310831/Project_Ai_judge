import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from ai_judge.main import create_app
from ai_judge.phase1.importers import Importer
from ai_judge.phase1.operations import Operations
from ai_judge.phase1.settings import Phase1Settings
from ai_judge.storage.repository import Repository
from ai_judge.storage.tables import attack_jobs, attacks


def import_body(client, raw, job_id=None):
    headers = {"content-type": "application/x-ndjson"}
    if job_id:
        headers["X-Job-ID"] = str(job_id)
    return client.post("/api/v1/attacks/import", content=raw, headers=headers)


def test_jsonl_import_and_query(database, attack):
    job_id = uuid4()
    with TestClient(create_app(database)) as client:
        body = (attack.model_dump_json() + "\n") * 2
        response = import_body(client, body, job_id)
        assert response.status_code == 201
        result = response.json()
        assert result["imported"] == 2
        assert len(set(result["ids"])) == 2
        job = client.get(f"/api/v1/attack-jobs/{job_id}").json()
        assert job["processed"] == job["total"] == 2
        assert job["status"] == "succeeded"
        assert import_body(client, body, job_id).status_code == 409
    with database.transaction() as connection:
        assert len(Repository(connection).list_attacks()) == 2


@pytest.mark.parametrize(
    "invalid",
    [
        b"{broken}",
        b"{}",
        b'{"subcategory":"x","attack_content":[1]}',
        b'{"subcategory":"x","attack_content":["x"],"subcategory":"y"}',
        b'{"subcategory":NaN,"attack_content":["x"]}',
        b"[]",
        b" ",
    ],
)
def test_invalid_line_is_atomic_and_redacted(database, attack, invalid):
    with TestClient(create_app(database)) as client:
        response = import_body(client, attack.model_dump_json().encode() + b"\n" + invalid)
        assert response.status_code == 422
        assert response.json()["details"][0]["record"] == 2
        job = client.get("/api/v1/attack-jobs/" + response.json()["job_id"]).json()
        assert job["status"] == "failed"
        assert "input" not in json.dumps(job)
    with database.transaction() as connection:
        assert Repository(connection).list_attacks() == []


def test_encoding_bom_limits_and_missing_job(database, attack):
    with TestClient(
        create_app(
            database,
            phase1_settings=Phase1Settings(
                _env_file=None,
                max_import_records=1,
                max_body_bytes=300,
            ),
        )
    ) as client:
        assert import_body(client, b"\xff").json()["error"] == "invalid_utf8"
        assert import_body(client, b"").status_code == 422
        assert (
            import_body(client, b"\xef\xbb\xbf" + attack.model_dump_json().encode()).status_code
            == 201
        )
        assert import_body(client, b"{}\n{}").json()["error"] == "invalid_record_count"
        assert import_body(client, b"x" * 301).status_code == 413
        assert client.post("/api/v1/attacks/import", json={}).status_code == 415
        assert client.get(f"/api/v1/attack-jobs/{uuid4()}").status_code == 404
        assert client.get("/api/v1/attack-jobs/not-uuid").status_code == 422


def test_database_failure_rolls_back_import(database, attack, monkeypatch):
    original = Repository.add_attacks

    def fail(self, records):
        ids = original(self, records)
        self.connection.execute(
            attacks.insert().values(
                id=ids[0],
                subcategory="synthetic",
                payload={},
            )
        )

    monkeypatch.setattr(Repository, "add_attacks", fail)
    status, result = Importer(Operations(database), Phase1Settings(_env_file=None)).attacks(
        attack.model_dump_json().encode()
    )
    assert status == 503
    assert result["error"] == "storage_unavailable"
    with database.transaction() as connection:
        assert connection.execute(sa.select(sa.func.count()).select_from(attacks)).scalar_one() == 0


def test_expired_jobs_are_visible_and_never_reexecuted(database):
    jid = uuid4()
    with database.transaction() as connection:
        repo = Repository(connection)
        assert repo.start_job(jid, "attack_import")
        connection.execute(
            attack_jobs.update()
            .where(attack_jobs.c.id == jid)
            .values(
                expires_at=datetime.now(UTC) - timedelta(seconds=1),
            )
        )
    assert Operations(database).get(jid)["status"] == "interrupted"
    assert Operations(database).execute("attack_import", jid, lambda _: pytest.fail())[0] == 409
