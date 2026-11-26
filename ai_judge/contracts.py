"""Shared wire contracts; persistence metadata never changes these field names."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class AttackData(Contract):
    subcategory: Text
    attack_content: list[Text] = Field(min_length=1)


class TemplateRound(Contract):
    round: int = Field(ge=1)
    objective: Text
    target_weakness: Text


class AttackTemplate(Contract):
    risk_subcategory: Text
    environment: Text
    power_relationship: Text
    rounds: list[TemplateRound] = Field(min_length=1)

    @model_validator(mode="after")
    def ordered_rounds(self) -> Self:
        if [item.round for item in self.rounds] != list(range(1, len(self.rounds) + 1)):
            raise ValueError("rounds must be ordered consecutively from 1")
        return self


class ModelOutput(Contract):
    situation: Text
    query: Text
    reasoning_steps: list[Text] = Field(min_length=1)
    final_response: Text


class JudgeResult(Contract):
    judge_model: Text
    rationale: Text
    safety_score: float = Field(ge=0, le=10)
    verdict: Literal["SAFE", "UNSAFE"]
    judge_version: Text
