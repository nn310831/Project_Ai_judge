from uuid import uuid4

import httpx
import pytest

from ai_judge.contracts import AttackData
from ai_judge.phase2.adapters import AdapterRegistry, OllamaAdapter
from ai_judge.phase2.configuration import ConfigurationService
from ai_judge.phase2.contracts import TargetConfig, TargetError
from ai_judge.phase2.loading import LoadingService, LoadRequest, Sample, SamplingSnapshot
from ai_judge.phase2.settings import TargetSettings
from ai_judge.storage.repository import Repository


def test_load_job_and_direct_snapshot_never_calls_inference(database):
    settings = TargetSettings(_env_file=None)
    config = TargetConfig(base_url="http://127.0.0.1:11434", model="test")
    config_id = ConfigurationService(database, settings).create(config)
    snapshot = SamplingSnapshot(
        samples=[
            Sample(
                id=uuid4(),
                data=AttackData(
                    subcategory="synthetic",
                    attack_content=["test"],
                ),
            )
        ],
        sampling={"k": 1, "seed": 42},
    )
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: pytest.fail("Unexpected inference"))
    ) as c:
        service = LoadingService(database, settings, AdapterRegistry({"ollama": OllamaAdapter(c)}))
        direct_id = service.load_snapshot(config_id, snapshot)
        assert service.get(direct_id).snapshot == snapshot
        jid = uuid4()
        with database.transaction() as connection:
            repo = Repository(connection)
            repo.start_job(jid, "sampling")
            repo.finish_job(jid, "succeeded", snapshot.model_dump(mode="json"))
        load_id = service.load_job(LoadRequest(model_config_id=config_id, sampling_job_id=jid))
        assert service.get(load_id).snapshot == snapshot
        snapshot.samples[0].data.attack_content.append("mutated locally")
        assert len(service.get(load_id).snapshot.samples[0].data.attack_content) == 1
        with pytest.raises(TargetError, match="sampling_job_not_found"):
            service.load_job(LoadRequest(model_config_id=config_id, sampling_job_id=uuid4()))


@pytest.mark.parametrize(
    "kind,status,result",
    [
        ("attack_import", "succeeded", {}),
        ("sampling", "failed", {}),
        ("sampling", "succeeded", {}),
    ],
)
def test_invalid_sampling_sources(database, kind, status, result):
    jid = uuid4()
    with database.transaction() as connection:
        repo = Repository(connection)
        repo.start_job(jid, kind)
        repo.finish_job(jid, status, result)
    service = LoadingService(database, TargetSettings(_env_file=None), AdapterRegistry({}))
    with pytest.raises(TargetError):
        service.load_job(LoadRequest(model_config_id=uuid4(), sampling_job_id=jid))


def test_ollama_protocol_and_registry():
    def handler(request):
        import json

        body = json.loads(request.content)
        assert str(request.url) == "http://127.0.0.1:11434/api/chat"
        assert body["stream"] is False
        assert body["format"]["required"] == [
            "situation",
            "query",
            "reasoning_steps",
            "final_response",
        ]
        assert body["options"]["num_predict"] == 2048
        return httpx.Response(
            200,
            json={
                "done": True,
                "done_reason": "stop",
                "message": {"content": "public JSON output"},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        registry = AdapterRegistry({"ollama": OllamaAdapter(c)})
        reply = registry.resolve("ollama").chat(
            TargetConfig(base_url="http://127.0.0.1:11434", model="test"),
            [{"role": "user", "content": "synthetic test"}],
        )
        assert reply.content == "public JSON output"
        assert not reply.mock
        with pytest.raises(TargetError, match="unsupported_provider"):
            registry.resolve("future")


@pytest.mark.parametrize(
    "mode,code",
    [
        ("timeout", "target_timeout"),
        ("http", "target_http_error"),
        ("invalid", "invalid_target_envelope"),
        ("incomplete", "target_incomplete_output"),
        ("empty", "target_empty_output"),
        ("refusal", "target_refused"),
    ],
)
def test_adapter_errors(mode, code):
    def handler(request):
        if mode == "timeout":
            raise httpx.ReadTimeout("sensitive", request=request)
        if mode == "http":
            return httpx.Response(500, text="sensitive")
        if mode == "invalid":
            return httpx.Response(200, json={})
        return httpx.Response(
            200,
            json={
                "done": mode != "incomplete",
                "message": {
                    "content": "" if mode == "empty" else "x",
                    "refusal": mode == "refusal",
                },
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(TargetError) as error:
            OllamaAdapter(c).chat(TargetConfig(base_url="http://127.0.0.1:11434", model="test"), [])
        assert error.value.code == ("target_incomplete_output" if mode == "invalid" else code)
        assert "sensitive" not in str(error.value)
