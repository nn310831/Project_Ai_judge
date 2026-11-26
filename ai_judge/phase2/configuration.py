from uuid import UUID

from ai_judge.phase2.contracts import TargetConfig, TargetError
from ai_judge.phase2.settings import TargetSettings
from ai_judge.storage.database import Database
from ai_judge.storage.target_repository import TargetRepository


class ConfigurationService:
    def __init__(self, database: Database, settings: TargetSettings):
        self.database, self.settings = database, settings

    def validate_endpoint(self, config: TargetConfig):
        allowed = {url.rstrip("/") for url in self.settings.allowed_base_urls}
        if config.base_url not in allowed:
            raise TargetError("endpoint_not_allowed", 403)

    def create(self, config: TargetConfig) -> UUID:
        self.validate_endpoint(config)
        with self.database.transaction() as connection:
            return TargetRepository(connection).add_config(config.model_dump(mode="json"))

    def get(self, identifier: UUID) -> TargetConfig:
        with self.database.transaction() as connection:
            row = TargetRepository(connection).get_config(identifier)
        if row is None:
            raise TargetError("model_config_not_found", 404)
        config = TargetConfig.model_validate(row["payload"])
        self.validate_endpoint(config)
        return config
