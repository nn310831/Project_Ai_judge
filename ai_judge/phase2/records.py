from uuid import UUID, uuid4

from pydantic import ValidationError

from ai_judge.contracts import Contract
from ai_judge.phase2.adapters import AdapterRegistry
from ai_judge.phase2.contracts import Identifier, OllamaParameters, TargetConfig, TargetError
from ai_judge.phase2.loading import LoadingService
from ai_judge.phase2.settings import TargetSettings
from ai_judge.storage.database import Database
from ai_judge.storage.run_repository import RunRepository


class TestRequest(Contract):
    __test__ = False
    load_id: Identifier
    sliding_window: bool = False
    model_parameters: OllamaParameters | None = None
    use_mock: bool = False


class RunService:
    def __init__(self, database: Database, settings: TargetSettings, registry: AdapterRegistry):
        self.database, self.settings = database, settings
        self.loader = LoadingService(database, settings, registry)

    def submit(self, request: TestRequest, run_id: UUID | None = None) -> UUID:
        loaded = self.loader.get(request.load_id)
        self.loader.configurations.validate_endpoint(loaded.configuration)
        self.loader.registry.resolve(loaded.configuration.provider)
        config = loaded.configuration.model_dump()
        if request.model_parameters is not None:
            config["parameters"].update(request.model_parameters.model_dump(exclude_unset=True))
        try:
            effective = TargetConfig.model_validate(config)
        except ValidationError:
            raise TargetError("invalid_effective_parameters") from None
        if request.use_mock and not self.settings.mock_enabled:
            raise TargetError("target_mock_not_enabled", 403)
        loaded.configuration = effective
        identifier = run_id or uuid4()
        payload = {
            "loaded": loaded.model_dump(mode="json"),
            "sliding_window": request.sliding_window,
            "mock": request.use_mock,
            "max_attempts_per_round": 1,
        }
        with self.database.transaction() as connection:
            if not RunRepository(connection).enqueue(identifier, request.load_id, payload):
                raise TargetError("run_id_exists", 409)
        return identifier

    def status(self, run_id: UUID) -> dict:
        with self.database.transaction() as connection:
            run = RunRepository(connection).get(run_id)
        if run is None:
            raise TargetError("run_not_found", 404)
        payload = run.pop("payload")
        run.pop("owner")
        config = payload["loaded"]["configuration"]
        run["execution"] = {
            "model_config_id": payload["loaded"]["model_config_id"],
            "provider": config["provider"],
            "model": config["model"],
            "parameters": config["parameters"],
            "mock": payload["mock"],
            "sliding_window": payload["sliding_window"],
            "max_attempts_per_round": 1,
        }
        return run

    def cases(self, run_id: UUID, limit: int = 20, offset: int = 0):
        self.status(run_id)
        with self.database.transaction() as connection:
            return RunRepository(connection).list_cases(run_id, limit, offset)

    def rounds(self, run_id: UUID, case_id: UUID, limit: int = 20, offset: int = 0):
        self.status(run_id)
        with self.database.transaction() as connection:
            return RunRepository(connection).list_rounds(run_id, case_id, limit, offset)
