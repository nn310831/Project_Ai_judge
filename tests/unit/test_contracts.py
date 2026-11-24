import pytest
from pydantic import ValidationError

from ai_judge.contracts import AttackData, AttackTemplate, JudgeResult, ModelOutput


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"subcategory": "x", "attack_content": []},
        {"subcategory": " ", "attack_content": ["x"]},
        {"subcategory": "x", "attack_content": [1]},
        {"subcategory": "x", "attack_content": ["x"], "extra": True},
        {"risk_subcategory": "x", "attack_content": ["x"]},
    ],
)
def test_invalid_attack(value):
    with pytest.raises(ValidationError):
        AttackData.model_validate(value)


@pytest.mark.parametrize("rounds", [[2], [1, 1], [2, 1], [1, 3], [], [True]])
def test_round_order(template, rounds):
    value = template.model_dump()
    value["rounds"] = [dict(round=r, objective="x", target_weakness="y") for r in rounds]
    with pytest.raises(ValidationError):
        AttackTemplate.model_validate(value)


def test_wire_contract_round_trip(attack, template):
    assert AttackData.model_validate_json(attack.model_dump_json()) == attack
    assert AttackTemplate.model_validate_json(template.model_dump_json()) == template
    result = ModelOutput(
        situation="s", query="q", reasoning_steps=["observable"], final_response="f"
    )
    assert set(result.model_dump()) == {"situation", "query", "reasoning_steps", "final_response"}
    with pytest.raises(ValidationError):
        ModelOutput(situation="s", query="q", reasoning_steps=[], final_response="f")


@pytest.mark.parametrize("score", [-1, 11, "5", float("nan"), float("inf"), True])
def test_invalid_judge_score(score):
    with pytest.raises(ValidationError):
        JudgeResult(
            judge_model="test",
            rationale="test",
            safety_score=score,
            verdict="SAFE",
            judge_version="test-only",
        )


def test_judge_contract():
    assert (
        JudgeResult(
            judge_model="test",
            rationale="test",
            safety_score=10,
            verdict="SAFE",
            judge_version="test-only",
        ).safety_score
        == 10
    )
    with pytest.raises(ValidationError):
        JudgeResult(
            judge_model="test",
            rationale="test",
            safety_score=5,
            verdict="unknown",
            judge_version="test-only",
        )
