import json
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ai_judge.contracts import AttackData
from ai_judge.main import create_app
from ai_judge.phase1.errors import OperationError
from ai_judge.phase1.generation import (
    ChatCompletionsGenerator,
    GenAISettings,
    GenerationRequest,
    GenerationService,
)
from ai_judge.phase1.operations import Operations
from ai_judge.storage.repository import Repository


def configured(**kwargs):
    return GenAISettings(
        _env_file=None,
        enabled=True,
        base_url="https://example.test/v1",
        api_key="test-only-token",
        model="test-model",
        **kwargs,
    )


def envelope(template):
    return {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": json.dumps(
                        {
                            "subcategory": template.risk_subcategory,
                            "attack_content": ["合成測試" for _ in template.rounds],
                        }
                    )
                },
            }
        ]
    }


def test_http_adapter_request_and_generation_trace(database, template):
    with database.transaction() as connection:
        tid = Repository(connection).add_template(template)
        other = template.model_copy(update={"risk_subcategory": "other"})
        Repository(connection).add_template(other)
    requests = []

    def handler(request):
        requests.append(request)
        body = json.loads(request.content)
        assert request.url == "https://example.test/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-only-token"
        assert body["model"] == "test-model"
        assert body["response_format"] == {"type": "json_object"}
        assert body["messages"][0]["role"] == "system"
        assert json.loads(body["messages"][1]["content"])["template"] == template.model_dump()
        return httpx.Response(200, json=envelope(template))

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        adapter = ChatCompletionsGenerator(configured(), http)
        with TestClient(create_app(database, generator=adapter)) as client:
            job_id = uuid4()
            response = client.post(
                "/api/v1/attacks/generate",
                json={"risk_subcategory": "synthetic"},
                headers={"X-Job-ID": str(job_id)},
            )
            assert response.status_code == 201
            result = response.json()
            assert result["generation"]["source_template_id"] == str(tid)
            assert result["generation"]["max_attempts"] == 1
            assert not result["generation"]["mock"]
            assert "test-only-token" not in response.text
            assert (
                client.post(
                    "/api/v1/attacks/generate",
                    json={"risk_subcategory": "synthetic"},
                    headers={"X-Job-ID": str(job_id)},
                ).status_code
                == 409
            )
            assert (
                client.get(f"/api/v1/attack-jobs/{job_id}").json()["result"]["id"] == result["id"]
            )
    assert len(requests) == 1
    with database.transaction() as connection:
        saved = Repository(connection).get_attack(UUID(result["id"]))
        assert saved.source_template_id == tid


def test_no_candidates_never_calls_provider(database):
    class Never:
        def generate(self, _):
            pytest.fail("No candidates must not call provider")

    status, result = GenerationService(Operations(database), Never()).generate(
        GenerationRequest(risk_subcategory="absent")
    )
    assert status == 404
    assert result["error"] == "no_template_candidates"


@pytest.mark.parametrize(
    "mode,expected,status",
    [
        ("timeout", "provider_timeout", 504),
        ("network", "provider_connection_error", 502),
        ("http", "provider_http_error", 502),
        ("redirect", "provider_http_error", 502),
        ("invalid_json", "invalid_generated_output", 502),
        ("missing_choices", "invalid_generated_output", 502),
        ("missing_field", "invalid_generated_output", 502),
        ("bad_type", "invalid_generated_output", 502),
        ("refusal", "provider_refused", 502),
        ("incomplete", "provider_incomplete_output", 502),
        ("category", "generated_category_mismatch", 502),
        ("rounds", "generated_round_count_mismatch", 502),
    ],
)
def test_provider_errors_are_recorded_without_saving(database, template, mode, expected, status):
    with database.transaction() as connection:
        Repository(connection).add_template(template)
    calls = []

    def handler(request):
        calls.append(request)
        if mode == "timeout":
            raise httpx.ReadTimeout("test-only-token", request=request)
        if mode == "network":
            raise httpx.ConnectError("test-only-token", request=request)
        if mode == "http":
            return httpx.Response(429, text="test-only-token")
        if mode == "redirect":
            return httpx.Response(302, headers={"location": "https://elsewhere.test"})
        if mode == "invalid_json":
            return httpx.Response(200, text="test-only-token")
        if mode == "missing_choices":
            return httpx.Response(200, json={})
        body = envelope(template)
        choice = body["choices"][0]
        if mode == "refusal":
            choice["message"]["refusal"] = "test-only-token"
        elif mode == "incomplete":
            choice["finish_reason"] = "length"
        else:
            data = json.loads(choice["message"]["content"])
            if mode == "category":
                data["subcategory"] = "different"
            elif mode == "rounds":
                data["attack_content"] *= 2
            elif mode == "bad_type":
                data["attack_content"] = [1]
            elif mode == "missing_field":
                del data["subcategory"]
            choice["message"]["content"] = json.dumps(data)
        return httpx.Response(200, json=body)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        service = GenerationService(
            Operations(database), ChatCompletionsGenerator(configured(), client)
        )
        actual_status, result = service.generate(GenerationRequest(risk_subcategory="synthetic"))
    assert actual_status == status
    assert result["error"] == expected
    assert "test-only-token" not in json.dumps(result)
    assert len(calls) == 1
    with database.transaction() as connection:
        repo = Repository(connection)
        assert repo.list_attacks() == []
        assert repo.get_job(UUID(result["job_id"]))["status"] == "failed"


def test_disabled_unconfigured_busy_and_response_limit(template):
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text="x" * 200))
    ) as c:
        for settings, expected in [
            (GenAISettings(_env_file=None), "generation_disabled"),
            (GenAISettings(_env_file=None, enabled=True), "generation_not_configured"),
            (configured(max_response_bytes=100), "provider_response_too_large"),
        ]:
            with pytest.raises(OperationError) as error:
                ChatCompletionsGenerator(settings, c).generate(template)
            assert error.value.code == expected
        adapter = ChatCompletionsGenerator(configured(max_concurrency=1), c)
        adapter.slots.acquire()
        with pytest.raises(OperationError, match="generation_busy"):
            adapter.generate(template)
        adapter.slots.release()


def test_config_secrets_and_category_request():
    assert "test-only-token" not in repr(configured())
    with pytest.raises(ValidationError):
        GenAISettings(_env_file=None, base_url="https://user:secret@example.test/v1")
    with pytest.raises(ValidationError):
        GenerationRequest(risk_subcategory=" ")


def test_replaceable_generator(database, template):
    class Fake:
        def metadata(self):
            return {"provider": "test-double", "mock": True}

        def generate(self, data):
            return AttackData(subcategory=data.risk_subcategory, attack_content=["合成資料"])

    with database.transaction() as connection:
        Repository(connection).add_template(template)
    status, result = GenerationService(Operations(database), Fake()).generate(
        GenerationRequest(risk_subcategory="synthetic")
    )
    assert status == 201
    assert result["generation"]["mock"]
