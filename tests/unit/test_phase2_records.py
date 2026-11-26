from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from ai_judge.main import create_app
from ai_judge.phase2.configuration import ConfigurationService
from ai_judge.phase2.contracts import OllamaParameters, TargetError
from ai_judge.phase2.records import RunService, TestRequest
from ai_judge.storage.run_repository import RunRepository
from ai_judge.storage.tables import target_runs


def test_submit_snapshot_override_and_duplicate(database, target_setup):
    load_id, settings, registry, case_id, config_id = target_setup
    service = RunService(database, settings, registry)
    run_id = uuid4()
    service.submit(
        TestRequest(load_id=load_id, model_parameters=OllamaParameters(temperature=0.2)), run_id
    )
    status = service.status(run_id)
    assert status["status"] == "queued"
    assert status["execution"]["parameters"]["temperature"] == 0.2
    assert ConfigurationService(database, settings).get(config_id).parameters.temperature == 0.7
    with pytest.raises(TargetError, match="run_id_exists"):
        service.submit(TestRequest(load_id=load_id), run_id)
    assert service.cases(run_id)[0]["case_id"] == case_id


def test_record_success_and_failure_and_query(database, target_setup):
    load_id, settings, registry, case_id, _ = target_setup
    service = RunService(database, settings, registry)
    run_id = service.submit(TestRequest(load_id=load_id))
    owner = uuid4()
    with database.transaction() as connection:
        repo = RunRepository(connection)
        assert repo.claim(owner)["id"] == run_id
        assert repo.claim(uuid4()) is None
        repo.begin_round(run_id, owner, case_id, 1, {"query": "first", "parameters": {}}, 1)
        repo.finish_round(
            run_id,
            owner,
            case_id,
            1,
            status="succeeded",
            elapsed_ms=5,
            response={"content": "synthetic"},
        )
    with database.transaction() as connection:
        repo = RunRepository(connection)
        repo.begin_round(run_id, owner, case_id, 2, {"query": "second", "parameters": {}}, 1)
        repo.finish_round(
            run_id, owner, case_id, 2, status="failed", elapsed_ms=10, error="target_timeout"
        )
        repo.finish_case(run_id, owner, case_id, "target_timeout")
        repo.finish_run(run_id, owner)
    assert service.status(run_id)["status"] == "failed"
    headers = {"Authorization": "Bearer test-only-token"}
    with TestClient(create_app(database, target_settings=settings)) as client:
        base = f"/api/v1/target-models/test/ollama/{run_id}"
        assert client.get(base, headers=headers).json()["completed_cases"] == 1
        rows = client.get(
            base + f"/cases/{case_id}/rounds?limit=1&offset=1", headers=headers
        ).json()["items"]
        assert len(rows) == 1 and rows[0]["error"] == "target_timeout"
        assert client.get(base + "/cases?limit=0", headers=headers).status_code == 422
        assert client.get(base).status_code == 401


def test_expired_worker_keeps_records_and_cannot_reclaim_or_write(database, target_setup):
    load_id, settings, registry, case_id, _ = target_setup
    service = RunService(database, settings, registry)
    run_id = service.submit(TestRequest(load_id=load_id))
    owner = uuid4()
    with database.transaction() as connection:
        repo = RunRepository(connection)
        repo.claim(owner)
        repo.begin_round(run_id, owner, case_id, 1, {"query": "pending"}, 1)
        connection.execute(
            target_runs.update()
            .where(target_runs.c.id == run_id)
            .values(
                lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
            )
        )
    with database.transaction() as connection:
        repo = RunRepository(connection)
        assert repo.reap_expired() == [run_id]
        assert repo.claim(uuid4()) is None
        with pytest.raises(TargetError, match="run_lease_lost"):
            repo.renew(run_id, owner)
    assert service.status(run_id)["status"] == "interrupted"
    assert service.rounds(run_id, case_id)[0]["error"] == "inference_state_unknown"


def test_effective_params_and_mock_controls(database, target_setup):
    load_id, settings, registry, _, _ = target_setup
    service = RunService(database, settings, registry)
    with pytest.raises(TargetError, match="invalid_effective_parameters"):
        service.submit(TestRequest(load_id=load_id, model_parameters=OllamaParameters(num_ctx=512)))
    settings.mock_enabled = False
    with pytest.raises(TargetError, match="target_mock_not_enabled"):
        service.submit(TestRequest(load_id=load_id, use_mock=True))
