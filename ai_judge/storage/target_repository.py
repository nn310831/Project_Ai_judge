from uuid import UUID, uuid4

import sqlalchemy as sa

from ai_judge.storage.tables import target_configs, target_loads


class TargetRepository:
    """C-1 transaction-bound persistence for block 2; no HTTP dependency."""

    def __init__(self, connection: sa.Connection):
        self.connection = connection

    def add_config(self, payload: dict) -> UUID:
        identifier = uuid4()
        self.connection.execute(target_configs.insert().values(id=identifier, payload=payload))
        return identifier

    def get_config(self, identifier: UUID) -> dict | None:
        row = (
            self.connection.execute(
                sa.select(target_configs).where(
                    target_configs.c.id == identifier,
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else dict(row)

    def add_load(self, model_config_id: UUID, payload: dict) -> UUID:
        identifier = uuid4()
        self.connection.execute(
            target_loads.insert().values(
                id=identifier,
                model_config_id=model_config_id,
                payload=payload,
            )
        )
        return identifier

    def get_load(self, identifier: UUID) -> dict | None:
        row = (
            self.connection.execute(
                sa.select(target_loads).where(
                    target_loads.c.id == identifier,
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else dict(row)
