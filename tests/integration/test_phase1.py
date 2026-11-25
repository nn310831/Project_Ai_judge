import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import UUID, uuid4

import httpx
import pytest
from alembic import command
from fastapi.testclient import TestClient

from ai_judge.contracts import AttackData
from ai_judge.main import create_app
from ai_judge.phase1.generation import ChatCompletionsGenerator, GenAISettings
from ai_judge.storage.repository import Repository

pytestmark = pytest.mark.integration


def test_block1_full_pipeline_and_restart(postgres, template):
    database, _ = postgres
    calls = []

    def respond(request):
        calls.append(request)
        data = AttackData(subcategory="synthetic", attack_content=["合成生成案例"])
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": data.model_dump_json(),
                        },
                    }
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        adapter = ChatCompletionsGenerator(
            GenAISettings(
                _env_file=None,
                enabled=True,
                base_url="https://example.test/v1",
                api_key="synthetic-test-token",
                model="synthetic-test-model",
            ),
            http,
        )
        with TestClient(create_app(database, generator=adapter)) as client:
            assert client.get("/health/ready").status_code == 200
            templates = client.post("/api/v1/attack-templates/import", json=template.model_dump())
            assert templates.status_code == 201
            template_id = templates.json()["ids"][0]
            imported = client.post(
                "/api/v1/attacks/import",
                headers={
                    "content-type": "application/x-ndjson",
                },
                content="\n".join(
                    AttackData(subcategory="synthetic", attack_content=[text]).model_dump_json()
                    for text in ["apple garden", "train timetable", "合成中文案例"]
                ),
            )
            assert imported.status_code == 201
            generated = client.post(
                "/api/v1/attacks/generate", json={"risk_subcategory": "synthetic"}
            )
            assert generated.status_code == 201
            assert generated.json()["generation"]["source_template_id"] == template_id
            sampled = client.post("/api/v1/attacks/sample", json={"k": 3, "seed": 123})
            assert sampled.status_code == 201
            assert len({item["id"] for item in sampled.json()["samples"]}) == 3
            expected_ids = set(imported.json()["ids"] + [generated.json()["id"]])
            assert set(sampled.json()["sampling"]["candidate_ids"]) == expected_ids
            again = client.post("/api/v1/attacks/sample", json={"k": 3, "seed": 123})
            assert again.json()["samples"] == sampled.json()["samples"]
            invalid = client.post(
                "/api/v1/attacks/import",
                headers={
                    "content-type": "application/x-ndjson",
                },
                content=AttackData(
                    subcategory="synthetic", attack_content=["not committed"]
                ).model_dump_json()
                + "\n{}",
            )
            assert invalid.status_code == 422
            job_id = sampled.json()["job_id"]
        database.close()
        with TestClient(create_app(database)) as restarted:
            job = restarted.get(f"/api/v1/attack-jobs/{job_id}").json()
            assert job["result"]["samples"] == sampled.json()["samples"]
            assert job["status"] == "succeeded"
    assert len(calls) == 1
    with database.transaction() as connection:
        repo = Repository(connection)
        assert len(repo.list_attacks()) == 4
        assert repo.get_attack(UUID(generated.json()["id"])).source_template_id == UUID(template_id)


def test_query_while_generation_runs_and_duplicate_id(postgres, template):
    database, _ = postgres
    entered, release = Event(), Event()

    class BlockingGenerator:
        def metadata(self):
            return {"provider": "test-double", "mock": True}

        def generate(self, data):
            entered.set()
            assert release.wait(5), "test did not release generator"
            return AttackData(subcategory=data.risk_subcategory, attack_content=["synthetic"])

    with database.transaction() as connection:
        Repository(connection).add_template(template)
    jid = uuid4()
    with TestClient(create_app(database, generator=BlockingGenerator())) as client:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(
                client.post,
                "/api/v1/attacks/generate",
                json={"risk_subcategory": "synthetic"},
                headers={"X-Job-ID": str(jid)},
            )
            try:
                assert entered.wait(5)
                assert client.get("/health/live").status_code == 200
                job = client.get(f"/api/v1/attack-jobs/{jid}").json()
                assert job["status"] == "running"
                assert job["processed"] == 0 and job["total"] == 1
                duplicate = client.post(
                    "/api/v1/attacks/generate",
                    json={"risk_subcategory": "synthetic"},
                    headers={"X-Job-ID": str(jid)},
                )
                assert duplicate.status_code == 409
                assert not pending.done()
            finally:
                release.set()
            assert pending.result(timeout=5).status_code == 201


def test_upgrade_from_common_preserves_data(postgres, attack, template):
    database, config = postgres
    with database.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "0001_common_storage")
    with database.transaction() as connection:
        repo = Repository(connection)
        tid = repo.add_template(template)
        aid = repo.add_attacks([attack], source_template_id=tid)[0]
    with database.engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    with database.transaction() as connection:
        repo = Repository(connection)
        assert repo.get_attack(aid).data == attack
        assert repo.get_attack(aid).source_template_id == tid
        assert repo.get_template(tid).data == template
    with TestClient(create_app(database)) as client:
        assert client.get("/health/ready").status_code == 200


def test_postgres_rejects_jsonl_batch_without_partial_writes(postgres, attack):
    database, _ = postgres
    with TestClient(create_app(database)) as client:
        result = client.post(
            "/api/v1/attacks/import",
            content=attack.model_dump_json() + "\n{}",
            headers={"content-type": "application/x-ndjson"},
        )
        assert result.status_code == 422
        job = client.get("/api/v1/attack-jobs/" + result.json()["job_id"]).json()
        assert job["status"] == "failed"
        assert job["result"]["details"][0]["record"] == 2
        assert "input" not in json.dumps(job)
    with database.transaction() as connection:
        assert Repository(connection).list_attacks() == []
