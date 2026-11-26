import json

import pytest

from ai_judge.contracts import ModelOutput
from ai_judge.phase2.adapters import TargetReply
from ai_judge.phase2.contracts import TargetError
from ai_judge.phase2.normalization import normalize_public_output, normalize_reply


def valid():
    return {
        "situation": "synthetic",
        "query": "question",
        "reasoning_steps": ["public explanation"],
        "final_response": "answer",
    }


def test_json_mapping_and_contract_have_identical_wire_output():
    expected = valid()
    for payload in [expected, json.dumps(expected), ModelOutput(**expected)]:
        assert normalize_public_output(payload).model_dump() == expected
    reply = normalize_reply(TargetReply(json.dumps(expected), "future-adapter", "model-v1", True))
    assert reply.output.model_dump() == expected
    assert reply.provider == "future-adapter" and reply.mock


@pytest.mark.parametrize("steps", [None, []])
def test_missing_reasoning_is_not_fabricated(steps):
    body = valid()
    body["reasoning_steps"] = steps
    with pytest.raises(TargetError, match="missing_reasoning_data"):
        normalize_public_output(body)
    del body["reasoning_steps"]
    with pytest.raises(TargetError, match="missing_reasoning_data"):
        normalize_public_output(body)


@pytest.mark.parametrize(
    "payload",
    [
        "```json\n{}\n```",
        "bad JSON",
        "[]",
        '{"x":1,"x":2}',
        {**valid(), "reasoning_steps": [1]},
        {**valid(), "reasoning_steps": [" "]},
        {**valid(), "final_response": ""},
        {**valid(), "unknown": True},
    ],
)
def test_invalid_outputs_fail_without_guessing(payload):
    with pytest.raises(TargetError, match="invalid_model_output"):
        normalize_public_output(payload)
