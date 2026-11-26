import hashlib
import json
import secrets
import unicodedata
from threading import BoundedSemaphore
from typing import Literal, Protocol
from uuid import UUID

import numpy as np
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from ai_judge.contracts import Contract, Text
from ai_judge.phase1.errors import OperationError
from ai_judge.phase1.kdpp import sample_k_dpp
from ai_judge.phase1.operations import Operations
from ai_judge.storage.repository import Repository


class SamplingRequest(Contract):
    k: int = Field(ge=1, le=500)
    subcategory: Text | None = None
    seed: int | None = Field(default=None, ge=0, le=2**63 - 1)


class SamplingSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AI_JUDGE_SAMPLING_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )
    representation: Literal["hashed_char_ngram_v1"] = "hashed_char_ngram_v1"
    dimensions: int = Field(default=256, ge=16, le=4096)
    ngram: int = Field(default=3, ge=1, le=5)
    kernel: Literal["rbf", "linear"] = "rbf"
    gamma: float = Field(default=1, gt=0, le=100, allow_inf_nan=False)
    quality_by_subcategory: dict[str, float] = Field(default_factory=dict)
    eigen_tolerance: float = Field(default=1e-10, ge=1e-14, le=1e-4, allow_inf_nan=False)
    max_candidates: int = Field(default=500, ge=1, le=500)
    max_text_characters: int = Field(default=10000, ge=1, le=100000)
    max_concurrency: int = Field(default=1, ge=1, le=4)

    @field_validator("quality_by_subcategory")
    @classmethod
    def valid_quality(cls, weights):
        if any(not np.isfinite(value) or not 0 <= value <= 1000 for value in weights.values()):
            raise ValueError("Quality weights must be finite values in 0..1000")
        return weights


class Encoder(Protocol):
    def encode(self, texts: list[str]) -> np.ndarray: ...

    def metadata(self) -> dict: ...


class HashedNgramEncoder:
    def __init__(self, dimensions: int, ngram: int):
        self.dimensions, self.ngram = dimensions, ngram

    def metadata(self) -> dict:
        return {
            "representation": "hashed_char_ngram_v1",
            "dimensions": self.dimensions,
            "ngram": self.ngram,
            "normalization": "NFKC-casefold-L2",
            "hash": "blake2b-128",
        }

    def encode(self, texts: list[str]) -> np.ndarray:
        features = np.zeros((len(texts), self.dimensions), dtype=np.float64)
        for row, text in enumerate(texts):
            normalized = unicodedata.normalize("NFKC", text).casefold()
            width = min(self.ngram, len(normalized))
            if not width:
                raise OperationError("empty_representation")
            for start in range(len(normalized) - width + 1):
                digest = hashlib.blake2b(
                    normalized[start : start + width].encode(), digest_size=16
                ).digest()
                column = int.from_bytes(digest[:8], "big") % self.dimensions
                features[row, column] += 1 if digest[8] & 1 else -1
            norm = np.linalg.norm(features[row])
            if norm == 0:
                raise OperationError("empty_representation")
            features[row] /= norm
        return features


class SamplingService:
    def __init__(
        self, operations: Operations, settings: SamplingSettings, encoder: Encoder | None = None
    ):
        self.operations, self.settings = operations, settings
        self.encoder = encoder or HashedNgramEncoder(settings.dimensions, settings.ngram)
        self.slots = BoundedSemaphore(settings.max_concurrency)

    def sample(self, request: SamplingRequest, job_id: UUID | None = None):
        return self.operations.execute("sampling", job_id, lambda jid: self._sample(request, jid))

    def _sample(self, request: SamplingRequest, job_id: UUID) -> dict:
        if not self.slots.acquire(blocking=False):
            raise OperationError("sampling_busy", 429)
        try:
            return self._run(request, job_id)
        finally:
            self.slots.release()

    def _run(self, request: SamplingRequest, job_id: UUID) -> dict:
        settings = self.settings
        with self.operations.database.transaction() as connection:
            candidates = Repository(connection).list_attacks(
                subcategory=request.subcategory,
                limit=settings.max_candidates + 1,
            )
        if len(candidates) > settings.max_candidates:
            raise OperationError("candidate_limit_exceeded")
        if len(candidates) < request.k:
            raise OperationError("insufficient_candidates")
        seed = request.seed if request.seed is not None else secrets.randbits(63)
        candidate_ids = [str(item.id) for item in candidates]
        texts = ["\n".join(item.data.attack_content) for item in candidates]
        metadata = {
            **settings.model_dump(),
            **self.encoder.metadata(),
            "seed": seed,
            "rng": "PCG64",
            "numpy_version": np.__version__,
            "algorithm": "spectral-k-dpp-v1",
            "candidate_ids": candidate_ids,
            "subcategory": request.subcategory,
            "candidate_payload_sha256": hashlib.sha256(
                json.dumps(
                    [item.data.model_dump() for item in candidates],
                    sort_keys=True,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest(),
            "k": request.k,
        }
        self.operations.progress(job_id, 0, request.k)
        try:
            if any(len(text) > settings.max_text_characters for text in texts):
                raise OperationError("candidate_text_too_long")
            features = np.asarray(self.encoder.encode(texts), dtype=np.float64)
            if (
                features.ndim != 2
                or len(features) != len(candidates)
                or not np.isfinite(features).all()
            ):
                raise OperationError("invalid_representation")
            if settings.kernel == "linear":
                similarity = features @ features.T
            else:
                norms = np.square(features).sum(axis=1)
                distances = np.maximum(
                    norms[:, None] + norms[None, :] - 2 * features @ features.T, 0
                )
                similarity = np.exp(-settings.gamma * distances)
            quality = np.array(
                [
                    settings.quality_by_subcategory.get(item.data.subcategory, 1.0)
                    for item in candidates
                ]
            )
            kernel = quality[:, None] * similarity * quality[None, :]
            indices = sample_k_dpp(kernel, request.k, seed, settings.eigen_tolerance)
        except OperationError as error:
            error.details.append({"sampling": metadata})
            raise
        result = {
            "samples": [
                {"id": candidate_ids[index], "data": candidates[index].data.model_dump()}
                for index in indices
            ],
            "sampling": metadata,
        }
        with self.operations.database.transaction() as connection:
            repo = Repository(connection)
            repo.update_job_progress(job_id, request.k, request.k)
            repo.finish_job(job_id, "succeeded", result)
        return result
