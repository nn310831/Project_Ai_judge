import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from ai_judge.contracts import AttackData, ModelOutput
from ai_judge.main import create_app
from ai_judge.phase1.operations import Operations
from ai_judge.phase1.sampling import SamplingRequest, SamplingService, SamplingSettings
from ai_judge.phase2 import worker
from ai_judge.phase2.adapters import AdapterRegistry, OllamaAdapter, TargetReply
from ai_judge.phase2.configuration import ConfigurationService
from ai_judge.phase2.contracts import TargetConfig, TargetError
from ai_judge.phase2.loading import LoadingService, Sample, SamplingSnapshot
from ai_judge.phase2.records import RunService, TestRequest
from ai_judge.phase2.runner import TargetRunner
from ai_judge.phase2.settings import TargetSettings
from ai_judge.storage.repository import Repository
from ai_judge.storage.run_repository import RunRepository
from ai_judge.storage.tables import target_runs

pytestmark = pytest.mark.integration
BASE = "/api/v1/target-models"
HEADERS = {"Authorization": "Bearer synthetic-test-token"}


def output(query):
    return ModelOutput(
        situation="synthetic",
        query=query,
        reasoning_steps=["public explanation"],
        final_response="synthetic answer",
    )


@pytest.fixture
def queued_setup(postgres):
    database, _ = postgres
    settings = TargetSettings(_env_file=None, mock_enabled=True, api_token="synthetic-test-token")
    registry = AdapterRegistry({"ollama": object()})
    config_id = ConfigurationService(database, settings).create(
        TargetConfig(base_url="http://127.0.0.1:11434", model="synthetic")
    )
    case_id = uuid4()
    load_id = LoadingService(database, settings, registry).load_snapshot(
        config_id,
        SamplingSnapshot(
            samples=[
                Sample(
                    id=case_id,
                    data=AttackData(subcategory="synthetic", attack_content=["first", "second"]),
                )
            ],
            sampling={"k": 1, "seed": 42},
        ),
    )
    return database, settings, registry, load_id, case_id


def test_block2_sampling_api_worker_and_restart(postgres):
    database, _ = postgres
    settings = TargetSettings(_env_file=None, api_token="synthetic-test-token")
    with database.transaction() as connection:
        Repository(connection).add_attacks(
            [
                AttackData(subcategory="synthetic", attack_content=["apple garden", "next apple"]),
                AttackData(
                    subcategory="synthetic", attack_content=["train timetable", "next train"]
                ),
            ]
        )
    code, sampled = SamplingService(Operations(database), SamplingSettings(_env_file=None)).sample(
        SamplingRequest(k=2, seed=42)
    )
    assert code == 201
    calls = []

    def respond(request):
        assert str(request.url) == "http://127.0.0.1:11434/api/chat"
        body = json.loads(request.content)
        calls.append(body)
        assert body["stream"] is False and body["options"]["temperature"] == 0.2
        return httpx.Response(
            200,
            json={
                "done": True,
                "done_reason": "stop",
                "model": "synthetic",
                "message": {
                    "content": output(body["messages"][-1]["content"]).model_dump_json(),
                    "thinking": "private provider field must not be saved",
                },
            },
        )

    with TestClient(create_app(database, target_settings=settings)) as client:
        configured = client.post(
            BASE + "/config/ollama",
            headers=HEADERS,
            json={"base_url": "http://127.0.0.1:11434", "model": "synthetic"},
        )
        assert configured.status_code == 201
        config_id = configured.json()["model_config_id"]
        loaded = client.post(
            BASE + "/load/ollama",
            headers=HEADERS,
            json={"model_config_id": config_id, "sampling_job_id": sampled["job_id"]},
        )
        assert loaded.status_code == 201
        submitted = client.post(
            BASE + "/test/ollama",
            headers=HEADERS,
            json={
                "load_id": loaded.json()["load_id"],
                "sliding_window": True,
                "model_parameters": {"temperature": 0.2},
            },
        )
        assert submitted.status_code == 202 and not calls
    # Inference works after the FastAPI lifespan has ended.
    database.close()
    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        registry = AdapterRegistry({"ollama": OllamaAdapter(http)})
        assert TargetRunner(database, settings, registry).run_once()
    assert [len(call["messages"]) for call in calls] == [2, 4, 2, 4]
    database.close()
    with TestClient(create_app(database, target_settings=settings)) as restarted:
        url = submitted.json()["status_url"]
        status = restarted.get(url, headers=HEADERS).json()
        assert status["status"] == "succeeded" and status["completed_cases"] == 2
        cases = restarted.get(url + "/cases", headers=HEADERS).json()["items"]
        assert [case["attack"] for case in cases] == [item["data"] for item in sampled["samples"]]
        for case in cases:
            rounds = restarted.get(
                url + f"/cases/{case['case_id']}/rounds", headers=HEADERS
            ).json()["items"]
            assert [row["round_number"] for row in rounds] == [1, 2]
            assert all(row["status"] == "succeeded" and row["attempts"] == 1 for row in rounds)
            assert rounds[0]["evidence"]["output"] == rounds[0]["response"]["output"]
            assert rounds[0]["evidence"]["source"] == "model_public_output"
            assert "private provider field" not in json.dumps(rounds)
        saved = restarted.get(BASE + f"/config/ollama/{config_id}", headers=HEADERS).json()
        assert saved["configuration"]["parameters"]["temperature"] == 0.7
    assert len(calls) == 4


def test_concurrent_workers_and_query_do_not_repeat_inference(queued_setup):
    database, settings, _, load_id, _ = queued_setup
    entered, release = Event(), Event()
    calls = []

    class BlockingAdapter:
        def chat(self, config, messages):
            calls.append(messages)
            entered.set()
            assert release.wait(5)
            return TargetReply(
                output(messages[-1]["content"]).model_dump_json(), "ollama", config.model
            )

    registry = AdapterRegistry({"ollama": BlockingAdapter()})
    service = RunService(database, settings, registry)
    run_id = service.submit(TestRequest(load_id=load_id))
    with ThreadPoolExecutor(max_workers=2) as pool:
        running = pool.submit(TargetRunner(database, settings, registry).run_once)
        try:
            assert entered.wait(5)
            assert service.status(run_id)["status"] == "running"
            assert not pool.submit(TargetRunner(database, settings, registry).run_once).result(5)
            assert len(calls) == 1
        finally:
            release.set()
        assert running.result(5)
    assert len(calls) == 2 and service.status(run_id)["status"] == "succeeded"


def test_concurrent_duplicate_submission_is_atomic(queued_setup):
    database, settings, registry, load_id, _ = queued_setup
    service = RunService(database, settings, registry)
    run_id, barrier = uuid4(), Barrier(2)

    def submit():
        barrier.wait(timeout=5)
        try:
            service.submit(TestRequest(load_id=load_id), run_id)
            return "accepted"
        except TargetError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: submit(), range(2)))
    assert sorted(results) == ["accepted", "run_id_exists"]
    assert len(service.cases(run_id)) == 1


def test_expired_worker_preserves_success_and_never_replays_unknown(queued_setup):
    database, settings, registry, load_id, case_id = queued_setup
    service = RunService(database, settings, registry)
    run_id = service.submit(TestRequest(load_id=load_id))
    owner = uuid4()
    with database.transaction() as connection:
        repo = RunRepository(connection)
        assert repo.claim(owner)["id"] == run_id
        repo.begin_round(run_id, owner, case_id, 1, {"query": "first"}, 1)
        repo.finish_round(
            run_id,
            owner,
            case_id,
            1,
            status="succeeded",
            elapsed_ms=1,
            response={"content": "saved public output"},
        )
        repo.begin_round(run_id, owner, case_id, 2, {"query": "second"}, 1)
        connection.execute(
            target_runs.update()
            .where(target_runs.c.id == run_id)
            .values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    database.close()
    assert not TargetRunner(database, settings, registry).run_once()
    assert service.status(run_id)["status"] == "interrupted"
    rows = service.rounds(run_id, case_id)
    assert rows[0]["response"]["content"] == "saved public output"
    assert rows[1]["error"] == "inference_state_unknown"
    with pytest.raises(TargetError, match="run_lease_lost"):
        with database.transaction() as connection:
            RunRepository(connection).finish_run(run_id, owner)


def test_worker_cli_runs_persisted_mock_without_fastapi(queued_setup, monkeypatch):
    database, settings, registry, load_id, case_id = queued_setup
    service = RunService(database, settings, registry)
    run_id = service.submit(TestRequest(load_id=load_id, use_mock=True))
    monkeypatch.setattr(worker, "TargetSettings", lambda: settings)
    monkeypatch.setattr(worker, "Settings", lambda: object())
    monkeypatch.setattr(worker, "create_database_engine", lambda _: database.engine)
    assert worker.main(["--once"]) == 0
    assert service.status(run_id)["status"] == "succeeded"
    assert all(row["evidence"]["mock"] for row in service.rounds(run_id, case_id))
