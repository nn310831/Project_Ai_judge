import json
from uuid import UUID

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from ai_judge.main import create_app
from ai_judge.phase1.settings import Phase1Settings
from ai_judge.storage.repository import Repository
from ai_judge.storage.tables import attack_templates


def test_single_and_batch_templates(database, template):
    with TestClient(create_app(database)) as client:
        single = client.post("/api/v1/attack-templates/import", json=template.model_dump())
        assert single.status_code == 201
        batch = client.post("/api/v1/attack-templates/import", json=[template.model_dump()] * 2)
        assert batch.status_code == 201
        assert batch.json()["imported"] == 2
        ids = single.json()["ids"] + batch.json()["ids"]
        assert len(set(ids)) == 3
        job = client.get("/api/v1/attack-jobs/" + batch.json()["job_id"]).json()
        assert job["kind"] == "template_import"
        assert job["processed"] == job["total"] == 2
    with database.transaction() as connection:
        for record_id in ids:
            assert Repository(connection).get_template(UUID(record_id)).data == template


@pytest.mark.parametrize("rounds", [[], [2], [1, 3], [2, 1], [1, 1], ["1"], [True]])
def test_invalid_template_rounds_reject_entire_batch(database, template, rounds):
    invalid = template.model_dump()
    invalid["rounds"] = [
        {"round": r, "objective": "test", "target_weakness": "test"} for r in rounds
    ]
    with TestClient(create_app(database)) as client:
        response = client.post(
            "/api/v1/attack-templates/import", json=[template.model_dump(), invalid]
        )
        assert response.status_code == 422
        assert response.json()["details"][0]["record"] == 2
    with database.transaction() as connection:
        assert (
            connection.execute(sa.select(sa.func.count()).select_from(attack_templates)).scalar()
            == 0
        )


@pytest.mark.parametrize(
    "raw,code",
    [
        (b"broken", "invalid_json"),
        (b"\xff", "invalid_utf8"),
        (b"[]", "invalid_record_count"),
        (b"{}", "invalid_records"),
        (b"null", "invalid_records"),
        (b'{"rounds":[],"rounds":[]}', "invalid_json"),
    ],
)
def test_bad_template_input(database, raw, code):
    with TestClient(create_app(database)) as client:
        response = client.post(
            "/api/v1/attack-templates/import",
            content=raw,
            headers={"content-type": "application/json"},
        )
        assert response.status_code == 422
        assert response.json()["error"] == code


def test_template_limits_and_content_type(database, template):
    with TestClient(
        create_app(
            database,
            phase1_settings=Phase1Settings(
                _env_file=None,
                max_import_records=1,
            ),
        )
    ) as client:
        assert (
            client.post("/api/v1/attack-templates/import", json=[template.model_dump()] * 2).json()[
                "error"
            ]
            == "invalid_record_count"
        )
        assert (
            client.post("/api/v1/attack-templates/import", content=json.dumps({})).status_code
            == 415
        )
