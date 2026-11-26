from dataclasses import dataclass
from time import monotonic
from typing import Protocol

import httpx

from ai_judge.contracts import ModelOutput
from ai_judge.phase1.importers import strict_json
from ai_judge.phase2.contracts import TargetConfig, TargetError


@dataclass(frozen=True)
class TargetReply:
    content: str
    provider: str
    model: str
    mock: bool = False
    metadata: dict | None = None


class TargetAdapter(Protocol):
    def chat(self, config: TargetConfig, messages: list[dict[str, str]]) -> TargetReply: ...


class AdapterRegistry:
    def __init__(self, adapters: dict[str, TargetAdapter]):
        self.adapters = dict(adapters)

    def resolve(self, provider: str) -> TargetAdapter:
        if provider not in self.adapters:
            raise TargetError("unsupported_provider")
        return self.adapters[provider]


class OllamaAdapter:
    def __init__(self, client: httpx.Client):
        self.client = client

    def chat(self, config: TargetConfig, messages: list[dict[str, str]]) -> TargetReply:
        started = monotonic()
        try:
            with self.client.stream(
                "POST",
                config.base_url + "/api/chat",
                follow_redirects=False,
                json={
                    "model": config.model,
                    "messages": messages,
                    "stream": False,
                    "format": ModelOutput.model_json_schema(),
                    "options": config.parameters.model_dump(),
                },
                timeout=config.timeout_seconds,
            ) as response:
                if not 200 <= response.status_code < 300:
                    raise TargetError("target_http_error", 502)
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > config.max_response_bytes:
                        raise TargetError("target_response_too_large", 502)
                    if monotonic() - started > config.timeout_seconds:
                        raise TargetError("target_timeout", 504)
            data = strict_json(raw.decode("utf-8"))
            if data.get("error"):
                raise TargetError("target_provider_error", 502)
            if data.get("done") is not True or data.get("done_reason") not in (None, "stop"):
                raise TargetError("target_incomplete_output", 502)
            message = data["message"]
            if message.get("refusal"):
                raise TargetError("target_refused", 502)
            content = message["content"]
            if not isinstance(content, str) or not content.strip():
                raise TargetError("target_empty_output", 502)
            return TargetReply(
                content,
                "ollama",
                str(data.get("model", config.model)),
                metadata={
                    "done_reason": data.get("done_reason"),
                    "provider_elapsed_ms": round((monotonic() - started) * 1000),
                },
            )
        except httpx.TimeoutException:
            raise TargetError("target_timeout", 504) from None
        except httpx.HTTPError:
            raise TargetError("target_connection_error", 502) from None
        except (ValueError, TypeError, KeyError, IndexError, AttributeError, RecursionError):
            raise TargetError("invalid_target_envelope", 502) from None
