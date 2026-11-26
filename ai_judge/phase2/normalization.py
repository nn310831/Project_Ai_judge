from dataclasses import dataclass

from pydantic import ValidationError

from ai_judge.contracts import ModelOutput
from ai_judge.phase1.importers import strict_json
from ai_judge.phase2.adapters import TargetReply
from ai_judge.phase2.contracts import TargetError


def normalize_public_output(payload: str | dict | ModelOutput) -> ModelOutput:
    try:
        if isinstance(payload, str):
            value = strict_json(payload)
        elif isinstance(payload, ModelOutput):
            value = payload.model_dump()
        else:
            value = payload
        if isinstance(value, dict) and not value.get("reasoning_steps"):
            raise TargetError("missing_reasoning_data", 502)
        return ModelOutput.model_validate(value)
    except (ValueError, TypeError, RecursionError, ValidationError):
        raise TargetError("invalid_model_output", 502) from None


@dataclass(frozen=True)
class NormalizedReply:
    output: ModelOutput
    provider: str
    model: str
    mock: bool


def normalize_reply(reply: TargetReply) -> NormalizedReply:
    return NormalizedReply(
        normalize_public_output(reply.content), reply.provider, reply.model, reply.mock
    )
