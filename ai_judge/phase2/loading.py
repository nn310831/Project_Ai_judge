from typing import Self
from uuid import UUID

from pydantic import Field, ValidationError, model_validator

from ai_judge.contracts import AttackData, Contract
from ai_judge.phase2.adapters import AdapterRegistry
from ai_judge.phase2.configuration import ConfigurationService
from ai_judge.phase2.contracts import Identifier, TargetConfig, TargetError
from ai_judge.phase2.settings import TargetSettings
from ai_judge.storage.database import Database
from ai_judge.storage.repository import Repository
from ai_judge.storage.target_repository import TargetRepository


class Sample(Contract):
    id: Identifier
    data: AttackData


class SamplingSnapshot(Contract):
    samples: list[Sample] = Field(min_length=1, max_length=500)
    sampling: dict

    @model_validator(mode="after")
    def unique_and_complete(self) -> Self:
        if len({item.id for item in self.samples}) != len(self.samples):
            raise ValueError("Sampling IDs must be unique")
        if self.sampling.get("k") != len(self.samples):
            raise ValueError("Snapshot k must match sample count")
        return self


class LoadRequest(Contract):
    model_config_id: Identifier
    sampling_job_id: Identifier


class LoadedTarget(Contract):
    model_config_id: Identifier
    configuration: TargetConfig
    sampling_job_id: Identifier | None = None
    snapshot: SamplingSnapshot


class LoadingService:
    def __init__(self, database: Database, settings: TargetSettings, registry: AdapterRegistry):
        self.database, self.settings, self.registry = database, settings, registry
        self.configurations = ConfigurationService(database, settings)

    def load_job(self, request: LoadRequest) -> UUID:
        with self.database.transaction() as connection:
            job = Repository(connection).get_job(request.sampling_job_id)
        if job is None:
            raise TargetError("sampling_job_not_found", 404)
        if job["kind"] != "sampling" or job["status"] != "succeeded":
            raise TargetError("invalid_sampling_job")
        try:
            snapshot = SamplingSnapshot.model_validate(job["result"])
        except ValidationError:
            raise TargetError("invalid_sampling_snapshot") from None
        return self.load_snapshot(request.model_config_id, snapshot, request.sampling_job_id)

    def load_snapshot(
        self, model_config_id: UUID, snapshot: SamplingSnapshot, sampling_job_id: UUID | None = None
    ) -> UUID:
        """Direct entry for a future orchestrator; never re-samples or calls inference."""
        snapshot = SamplingSnapshot.model_validate(snapshot.model_dump())
        config = self.configurations.get(model_config_id)
        self.registry.resolve(config.provider)
        if len(snapshot.samples) > self.settings.max_cases:
            raise TargetError("too_many_cases")
        if any(
            len(sample.data.attack_content) > self.settings.max_rounds_per_case
            for sample in snapshot.samples
        ):
            raise TargetError("too_many_rounds")
        loaded = LoadedTarget(
            model_config_id=model_config_id,
            configuration=config,
            sampling_job_id=sampling_job_id,
            snapshot=snapshot,
        )
        with self.database.transaction() as connection:
            return TargetRepository(connection).add_load(
                model_config_id, loaded.model_dump(mode="json")
            )

    def get(self, load_id: UUID) -> LoadedTarget:
        with self.database.transaction() as connection:
            row = TargetRepository(connection).get_load(load_id)
        if row is None:
            raise TargetError("load_not_found", 404)
        return LoadedTarget.model_validate(row["payload"])
