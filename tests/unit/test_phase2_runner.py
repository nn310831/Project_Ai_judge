from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from ai_judge.contracts import AttackData, ModelOutput
from ai_judge.main import create_app
from ai_judge.phase2.adapters import AdapterRegistry, TargetReply
from ai_judge.phase2.configuration import ConfigurationService
from ai_judge.phase2.contracts import TargetConfig, TargetError
from ai_judge.phase2.loading import LoadingService, Sample, SamplingSnapshot
from ai_judge.phase2.records import RunService, TestRequest
from ai_judge.phase2.runner import TargetRunner
from ai_judge.phase2.settings import TargetSettings


class RecordingAdapter:
    def __init__(self, failure=None):
        self.messages = []
        self.failure = failure

    def chat(self, config, messages):
        self.messages.append(messages)
        query = messages[-1]["content"]
        if self.failure == "timeout":
            raise TargetError("target_timeout", 504)
        if self.failure == "invalid":
            return TargetReply("broken JSON", "ollama", config.model)
        if self.failure == "missing":
            return TargetReply(
                '{"situation":"s","query":"q","final_response":"f"}', "ollama", config.model
            )
        if self.failure == "unexpected":
            raise RuntimeError("do not expose this detail")
        output = ModelOutput(
            situation="synthetic",
            query=query,
            reasoning_steps=["public explanation"],
            final_response="answer",
        )
        return TargetReply(output.model_dump_json(), "ollama", config.model)


def test_submit_returns_202_without_call_and_worker_runs_in_order(database, target_setup):
    load_id, settings, _, case_id, _ = target_setup
    headers = {"Authorization": "Bearer test-only-token", "X-Job-ID": str(uuid4())}
    with TestClient(create_app(database, target_settings=settings)) as client:
        response = client.post(
            "/api/v1/target-models/test/ollama", json={"load_id": str(load_id)}, headers=headers
        )
        assert response.status_code == 202
        assert response.json()["status"] == "queued"
        assert (
            client.post(
                "/api/v1/target-models/test/ollama", json={"load_id": str(load_id)}, headers=headers
            ).status_code
            == 409
        )
        run_id = UUID(response.json()["run_id"])
        adapter = RecordingAdapter()
        runner = TargetRunner(database, settings, AdapterRegistry({"ollama": adapter}))
        assert runner.run_once()
        assert not runner.run_once()
        assert [len(messages) for messages in adapter.messages] == [2, 4]
        base = response.json()["status_url"]
        status = client.get(base, headers=headers).json()
        assert status["status"] == "succeeded" and status["completed_cases"] == 1
        rounds = client.get(base + f"/cases/{case_id}/rounds", headers=headers).json()["items"]
        assert len(rounds) == 2
        assert all(row["attempts"] == 1 and row["elapsed_ms"] >= 0 for row in rounds)
        assert rounds[0]["evidence"]["source"] == "model_public_output"
        assert rounds[1]["request"]["parameters"]["num_predict"] == 2048
        assert rounds[1]["evidence"]["run_id"] == str(run_id)
        assert len(adapter.messages) == 2  # GET never infers again.


@pytest.mark.parametrize(
    "failure,code",
    [
        ("timeout", "target_timeout"),
        ("invalid", "invalid_model_output"),
        ("missing", "missing_reasoning_data"),
        ("unexpected", "target_internal_error"),
    ],
)
def test_failure_records_failed_and_skipped_rounds_without_retry(
    database, target_setup, failure, code
):
    load_id, settings, _, case_id, _ = target_setup
    adapter = RecordingAdapter(failure)
    registry = AdapterRegistry({"ollama": adapter})
    service = RunService(database, settings, registry)
    run_id = service.submit(TestRequest(load_id=load_id))
    TargetRunner(database, settings, registry).run_once()
    assert len(adapter.messages) == 1
    assert service.status(run_id)["status"] == "failed"
    rows = service.rounds(run_id, case_id)
    assert [row["status"] for row in rows] == ["failed", "skipped"]
    assert rows[0]["error"] == code and rows[0]["evidence"] is None
    assert rows[1]["attempts"] == 0


def test_explicit_mock_is_marked_and_default_is_off(database, target_setup):
    load_id, settings, registry, case_id, _ = target_setup
    assert not TargetSettings(_env_file=None).mock_enabled
    service = RunService(database, settings, registry)
    run_id = service.submit(TestRequest(load_id=load_id, use_mock=True))
    TargetRunner(database, settings, registry).run_once()
    assert service.status(run_id)["status"] == "succeeded"
    assert all(
        row["response"]["mock"] and row["evidence"]["source"] == "mock_public_output"
        for row in service.rounds(run_id, case_id)
    )


@pytest.mark.parametrize("window,expected", [(True, [2, 4, 4, 4]), (False, [2, 4, 6, 8])])
def test_runner_uses_same_window_switch(database, target_setup, window, expected):
    _, settings, _, _, _ = target_setup
    config_id = ConfigurationService(database, settings).create(
        TargetConfig(
            base_url="http://127.0.0.1:11434",
            model="test",
            window_turns=1,
        )
    )
    adapter = RecordingAdapter()
    registry = AdapterRegistry({"ollama": adapter})
    snapshot = SamplingSnapshot(
        samples=[
            Sample(
                id=uuid4(),
                data=AttackData(
                    subcategory="synthetic",
                    attack_content=["q1", "q2", "q3", "q4"],
                ),
            )
        ],
        sampling={"k": 1},
    )
    load_id = LoadingService(database, settings, registry).load_snapshot(config_id, snapshot)
    service = RunService(database, settings, registry)
    run_id = service.submit(TestRequest(load_id=load_id, sliding_window=window))
    TargetRunner(database, settings, registry).run_once()
    assert service.status(run_id)["status"] == "succeeded"
    assert [len(messages) for messages in adapter.messages] == expected


def test_case_failure_does_not_contaminate_next_case(database, target_setup):
    _, settings, _, _, config_id = target_setup

    class FailFirst(RecordingAdapter):
        def chat(self, config, messages):
            if messages[-1]["content"] == "fail":
                raise TargetError("target_timeout", 504)
            return super().chat(config, messages)

    adapter = FailFirst()
    registry = AdapterRegistry({"ollama": adapter})
    samples = [
        Sample(id=uuid4(), data=AttackData(subcategory="synthetic", attack_content=queries))
        for queries in [["fail", "skipped"], ["second case"]]
    ]
    load_id = LoadingService(database, settings, registry).load_snapshot(
        config_id, SamplingSnapshot(samples=samples, sampling={"k": 2})
    )
    service = RunService(database, settings, registry)
    run_id = service.submit(TestRequest(load_id=load_id))
    TargetRunner(database, settings, registry).run_once()
    status = service.status(run_id)
    assert status["status"] == "partial"
    assert status["completed_cases"] == 2 and status["failed_cases"] == 1
    assert len(adapter.messages[0]) == 2


def test_context_failure_saved_before_any_inference(database, target_setup):
    _, settings, _, _, _ = target_setup
    config_id = ConfigurationService(database, settings).create(
        TargetConfig(
            base_url="http://127.0.0.1:11434",
            model="test",
            context_max_characters=512,
        )
    )
    adapter = RecordingAdapter()
    registry = AdapterRegistry({"ollama": adapter})
    sample = Sample(
        id=uuid4(), data=AttackData(subcategory="synthetic", attack_content=["x" * 513])
    )
    load_id = LoadingService(database, settings, registry).load_snapshot(
        config_id, SamplingSnapshot(samples=[sample], sampling={"k": 1})
    )
    service = RunService(database, settings, registry)
    run_id = service.submit(TestRequest(load_id=load_id, sliding_window=True))
    TargetRunner(database, settings, registry).run_once()
    assert not adapter.messages
    row = service.rounds(run_id, sample.id)[0]
    assert row["attempts"] == 0 and row["error"] == "context_limit_exceeded"
