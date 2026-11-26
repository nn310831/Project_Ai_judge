from uuid import uuid4

import pytest

from ai_judge.contracts import ModelOutput
from ai_judge.phase2.contracts import TargetError
from ai_judge.phase2.normalization import NormalizedReply
from ai_judge.phase2.reasoning import build_judging_input


@pytest.mark.parametrize("mock", [False, True])
def test_paths_receive_equal_independent_evidence(mock):
    output = ModelOutput(
        situation="s", query="q", reasoning_steps=[" first ", "second"], final_response="f"
    )
    run, case = uuid4(), uuid4()
    evidence = build_judging_input(NormalizedReply(output, "ollama", "test", mock), run, case, 2)
    a, b = evidence.as_path_input(), evidence.as_path_input()
    assert a == b
    assert a["source"] == ("mock_public_output" if mock else "model_public_output")
    assert a["steps"] == [{"index": 1, "text": " first "}, {"index": 2, "text": "second"}]
    assert a["output"] == output.model_dump()
    a["steps"][0]["text"] = "changed"
    a["output"]["reasoning_steps"][0] = "changed"
    assert b == evidence.as_path_input()
    assert b["run_id"] == str(run) and b["case_id"] == str(case)


def test_invalid_reasoning_does_not_become_evidence():
    output = ModelOutput.model_construct(
        situation="s", query="q", reasoning_steps=[], final_response="f"
    )
    with pytest.raises(TargetError, match="missing_reasoning_data"):
        build_judging_input(NormalizedReply(output, "ollama", "test", False), uuid4(), uuid4(), 1)
