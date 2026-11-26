from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ai_judge.main import create_app
from ai_judge.phase2.configuration import ConfigurationService
from ai_judge.phase2.contracts import TargetConfig, TargetError
from ai_judge.phase2.settings import TargetSettings


@pytest.fixture
def target_config():
    return TargetConfig(base_url="http://127.0.0.1:11434", model="synthetic-test-model")


def test_configuration_does_not_call_model(database, target_config, monkeypatch):
    monkeypatch.setattr(
        httpx.Client, "send", lambda *args, **kwargs: pytest.fail("Unexpected HTTP")
    )
    service = ConfigurationService(database, TargetSettings(_env_file=None))
    identifier = service.create(target_config)
    assert service.get(identifier) == target_config
    with pytest.raises(TargetError, match="model_config_not_found"):
        service.get(uuid4())


def test_config_auth_and_allowlist(database, target_config):
    settings = TargetSettings(_env_file=None, api_token="test-only-token")
    headers = {"Authorization": "Bearer test-only-token"}
    with TestClient(create_app(database, target_settings=settings)) as client:
        assert (
            client.post(
                "/api/v1/target-models/config/ollama", json=target_config.model_dump()
            ).status_code
            == 401
        )
        response = client.post(
            "/api/v1/target-models/config/ollama", json=target_config.model_dump(), headers=headers
        )
        assert response.status_code == 201
        assert "test-only-token" not in response.text
        record_id = response.json()["model_config_id"]
        assert (
            client.get(f"/api/v1/target-models/config/ollama/{record_id}", headers=headers).json()[
                "configuration"
            ]["model"]
            == target_config.model
        )
        body = target_config.model_dump()
        body["base_url"] = "http://unauthorized.test"
        assert (
            client.post(
                "/api/v1/target-models/config/ollama", json=body, headers=headers
            ).status_code
            == 403
        )
    with TestClient(create_app(database, target_settings=TargetSettings(_env_file=None))) as client:
        assert (
            client.post(
                "/api/v1/target-models/config/ollama", json=target_config.model_dump()
            ).status_code
            == 503
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"provider": "unknown"},
        {"base_url": "http://user:secret@localhost"},
        {"timeout_seconds": 0},
        {"model": " "},
        {"parameters": {"arbitrary": 1}},
        {"parameters": {"temperature": -1}},
        {"parameters": {"top_p": 2}},
        {"parameters": {"num_predict": True}},
        {"parameters": {"num_ctx": 1024}},
    ],
)
def test_configuration_rejects_invalid_options(target_config, changes):
    with pytest.raises(ValidationError):
        TargetConfig.model_validate({**target_config.model_dump(), **changes})
