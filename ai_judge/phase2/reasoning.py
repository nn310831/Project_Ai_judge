from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ai_judge.contracts import ModelOutput
from ai_judge.phase2.normalization import NormalizedReply, normalize_public_output


class ReasoningStep(BaseModel):
    model_config = ConfigDict(frozen=True)
    index: int = Field(ge=1)
    text: str


class JudgingInput(BaseModel):
    model_config = ConfigDict(frozen=True)
    run_id: UUID
    case_id: UUID
    round_number: int = Field(ge=1)
    provider: str
    model: str
    mock: bool
    source: Literal["model_public_output", "mock_public_output"]
    output: ModelOutput
    steps: tuple[ReasoningStep, ...]

    def as_path_input(self) -> dict:
        """Independent JSON-safe copies for A/B; neither path can mutate the other."""
        return self.model_dump(mode="json")


def build_judging_input(
    reply: NormalizedReply, run_id: UUID, case_id: UUID, round_number: int
) -> JudgingInput:
    output = normalize_public_output(reply.output)  # Revalidate; never fabricate missing steps.
    return JudgingInput(
        run_id=run_id,
        case_id=case_id,
        round_number=round_number,
        provider=reply.provider,
        model=reply.model,
        mock=reply.mock,
        source="mock_public_output" if reply.mock else "model_public_output",
        output=output,
        steps=tuple(
            ReasoningStep(index=index, text=text)
            for index, text in enumerate(output.reasoning_steps, 1)
        ),
    )
