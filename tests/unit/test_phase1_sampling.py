from collections import Counter
from itertools import combinations
from uuid import UUID

import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ai_judge.contracts import AttackData
from ai_judge.main import create_app
from ai_judge.phase1.errors import OperationError
from ai_judge.phase1.kdpp import sample_k_dpp
from ai_judge.phase1.operations import Operations
from ai_judge.phase1.sampling import (
    HashedNgramEncoder,
    SamplingRequest,
    SamplingService,
    SamplingSettings,
)
from ai_judge.storage.repository import Repository


def test_distribution_matches_determinant_probabilities():
    # Non-diagonal PSD kernel: uniform subset sampling cannot pass this check.
    kernel = np.array([[4.0, 1.5, 0.1], [1.5, 1.0, 0.2], [0.1, 0.2, 2.0]])
    subsets = list(combinations(range(3), 2))
    weights = np.array([np.linalg.det(kernel[np.ix_(subset, subset)]) for subset in subsets])
    probabilities = weights / weights.sum()
    counts = Counter(tuple(sorted(sample_k_dpp(kernel, 2, seed))) for seed in range(6000))
    for subset, probability in zip(subsets, probabilities, strict=True):
        assert abs(counts[subset] / 6000 - probability) < 0.025


def test_projection_excludes_identical_candidates():
    features = np.array([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
    for seed in range(100):
        result = sample_k_dpp(features @ features.T, 2, seed)
        assert len(set(result)) == 2
        assert 2 in result  # The pair (0, 1) has determinant zero.


def test_seed_cardinality_and_scaling():
    kernel = np.diag([1.0, 2.0, 3.0, 4.0])
    assert sample_k_dpp(kernel, 3, 42) == sample_k_dpp(kernel, 3, 42)
    assert sample_k_dpp(kernel, 3, 42) == sample_k_dpp(kernel * 1e200, 3, 42)
    assert sample_k_dpp(kernel, 3, 42) == sample_k_dpp(kernel * 1e-200, 3, 42)
    assert sorted(sample_k_dpp(kernel, 4, 42)) == [0, 1, 2, 3]


@pytest.mark.parametrize(
    "kernel,k,code",
    [
        (np.eye(2), 0, "invalid_k"),
        (np.eye(2), 3, "invalid_k"),
        (np.eye(2), True, "invalid_k"),
        (np.eye(2), 1.5, "invalid_k"),
        (np.array([[1.0, 2.0], [0.0, 1.0]]), 1, "non_symmetric_kernel"),
        (np.array([[1.0, 2.0], [2.0, 1.0]]), 1, "non_psd_kernel"),
        (np.ones((3, 3)), 2, "insufficient_kernel_rank"),
        (np.zeros((2, 2)), 1, "insufficient_kernel_rank"),
        (np.array([[np.nan]]), 1, "invalid_kernel"),
        (np.array([[np.inf]]), 1, "invalid_kernel"),
        (np.ones((2, 3)), 1, "invalid_kernel"),
    ],
)
def test_bad_kernels_and_k(kernel, k, code):
    with pytest.raises(OperationError, match=code):
        sample_k_dpp(kernel, k, 1)


def test_hash_encoder_unicode_and_normalization():
    encoder = HashedNgramEncoder(256, 3)
    values = encoder.encode(["ＡＢＣ", "abc", "合成中文第一輪", "短"])
    np.testing.assert_allclose(values[0], values[1])
    np.testing.assert_allclose(np.linalg.norm(values, axis=1), np.ones(4))
    np.testing.assert_array_equal(values, encoder.encode(["ＡＢＣ", "abc", "合成中文第一輪", "短"]))


def seed_data(database):
    with database.transaction() as connection:
        return Repository(connection).add_attacks(
            [
                AttackData(subcategory="synthetic", attack_content=["apple garden sunshine"]),
                AttackData(subcategory="synthetic", attack_content=["train station timetable"]),
                AttackData(subcategory="synthetic", attack_content=["合成中文資料，另一個場景"]),
                AttackData(subcategory="other", attack_content=["other"]),
            ]
        )


def test_sample_api_seed_category_and_persistent_result(database):
    ids = seed_data(database)
    with TestClient(create_app(database)) as client:
        request = {"k": 2, "subcategory": "synthetic", "seed": 42}
        first = client.post("/api/v1/attacks/sample", json=request)
        second = client.post("/api/v1/attacks/sample", json=request)
        assert first.status_code == second.status_code == 201
        result = first.json()
        assert result["samples"] == second.json()["samples"]
        assert len({item["id"] for item in result["samples"]}) == 2
        assert str(ids[-1]) not in result["sampling"]["candidate_ids"]
        assert result["sampling"]["seed"] == 42
        assert result["sampling"]["algorithm"] == "spectral-k-dpp-v1"
        job = client.get("/api/v1/attack-jobs/" + result["job_id"]).json()
        assert job["processed"] == job["total"] == 2
        assert job["result"]["samples"] == result["samples"]
        for invalid in [{"k": 0}, {"k": True}, {"k": 1, "seed": -1}]:
            assert client.post("/api/v1/attacks/sample", json=invalid).status_code == 422
        assert (
            client.post("/api/v1/attacks/sample", json={"k": 5}).json()["error"]
            == "insufficient_candidates"
        )


def test_limit_rank_and_zero_quality_errors(database, attack):
    with database.transaction() as connection:
        Repository(connection).add_attacks([attack] * 2)
    for settings, expected in [
        (SamplingSettings(_env_file=None, max_candidates=1), "candidate_limit_exceeded"),
        (SamplingSettings(_env_file=None), "insufficient_kernel_rank"),
        (
            SamplingSettings(_env_file=None, quality_by_subcategory={"synthetic": 0}),
            "insufficient_kernel_rank",
        ),
        (SamplingSettings(_env_file=None, max_text_characters=1), "candidate_text_too_long"),
    ]:
        status, result = SamplingService(Operations(database), settings).sample(
            SamplingRequest(k=2)
        )
        assert status == 422
        assert result["error"] == expected
        assert Operations(database).get(UUID(result["job_id"]))["status"] == "failed"


def test_alternative_encoder_and_kernel(database):
    seed_data(database)

    class IdentityEncoder:
        def metadata(self):
            return {"representation": "test-identity"}

        def encode(self, texts):
            return np.eye(len(texts))

    settings = SamplingSettings(
        _env_file=None, kernel="linear", quality_by_subcategory={"other": 0}
    )
    status, result = SamplingService(Operations(database), settings, IdentityEncoder()).sample(
        SamplingRequest(k=3, seed=1)
    )
    assert status == 201
    assert all(item["data"]["subcategory"] == "synthetic" for item in result["samples"])
    assert result["sampling"]["representation"] == "test-identity"


def test_invalid_quality_settings():
    for value in [-1, float("inf"), float("nan")]:
        with pytest.raises(ValidationError):
            SamplingSettings(_env_file=None, quality_by_subcategory={"x": value})
