from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import Connection

from ai_judge.contracts import AttackData, AttackTemplate
from ai_judge.storage.database import StorageError
from ai_judge.storage.tables import attack_jobs, attack_templates, attacks


class ReferenceError(ValueError):
    """The source template is absent or belongs to a different category."""


@dataclass(frozen=True)
class StoredTemplate:
    id: UUID
    data: AttackTemplate
    created_at: datetime


@dataclass(frozen=True)
class StoredAttack:
    id: UUID
    data: AttackData
    source_template_id: UUID | None
    created_at: datetime


class Repository:
    """All methods participate in the caller's Database.transaction()."""

    def __init__(self, connection: Connection):
        self.connection = connection

    def start_job(self, job_id: UUID, kind: str) -> bool:
        # Conflict-safe insertion prevents a concurrent duplicate paid API call.
        if self.connection.dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        result = self.connection.execute(
            insert(attack_jobs)
            .values(
                id=job_id,
                kind=kind,
                status="running",
                expires_at=datetime.now(UTC) + timedelta(minutes=10),
            )
            .on_conflict_do_nothing(index_elements=["id"])
            .returning(attack_jobs.c.id)
        )
        return result.scalar_one_or_none() is not None

    def update_job_progress(self, job_id: UUID, processed: int, total: int):
        self.connection.execute(
            attack_jobs.update()
            .where(
                attack_jobs.c.id == job_id,
                attack_jobs.c.status == "running",
            )
            .values(processed=processed, total=total)
        )

    def finish_job(self, job_id: UUID, status: str, result: dict):
        changed = self.connection.execute(
            attack_jobs.update()
            .where(
                attack_jobs.c.id == job_id,
                attack_jobs.c.status == "running",
            )
            .values(status=status, result=result, finished_at=datetime.now(UTC))
        )
        if changed.rowcount != 1:
            raise StorageError("Job is no longer running")

    def get_job(self, job_id: UUID) -> dict | None:
        row = (
            self.connection.execute(
                sa.select(attack_jobs).where(
                    attack_jobs.c.id == job_id,
                )
            )
            .mappings()
            .first()
        )
        return None if row is None else dict(row)

    def add_template(self, data: AttackTemplate) -> UUID:
        return self.add_templates([data])[0]

    def add_templates(self, data: list[AttackTemplate]) -> list[UUID]:
        validated = [AttackTemplate.model_validate(item.model_dump()) for item in data]
        ids = [uuid4() for _ in validated]
        if validated:
            self.connection.execute(
                attack_templates.insert(),
                [
                    {
                        "id": record_id,
                        "risk_subcategory": item.risk_subcategory,
                        "payload": item.model_dump(),
                    }
                    for record_id, item in zip(ids, validated, strict=True)
                ],
            )
        return ids

    def add_attacks(
        self,
        data: list[AttackData],
        *,
        source_template_id: UUID | None = None,
    ) -> list[UUID]:
        validated = [AttackData.model_validate(item.model_dump()) for item in data]
        if not validated:
            return []
        if source_template_id is not None:
            template = self.get_template(source_template_id)
            if template is None or any(
                item.subcategory != template.data.risk_subcategory for item in validated
            ):
                raise ReferenceError("Source template missing or category mismatch")
        ids = [uuid4() for _ in validated]
        self.connection.execute(
            attacks.insert(),
            [
                dict(
                    id=record_id,
                    subcategory=item.subcategory,
                    payload=item.model_dump(),
                    source_template_id=source_template_id,
                )
                for record_id, item in zip(ids, validated, strict=True)
            ],
        )
        return ids

    def get_template(self, record_id: UUID) -> StoredTemplate | None:
        row = (
            self.connection.execute(
                sa.select(attack_templates).where(attack_templates.c.id == record_id)
            )
            .mappings()
            .first()
        )
        return (
            None
            if row is None
            else StoredTemplate(
                row["id"],
                AttackTemplate.model_validate(row["payload"]),
                row["created_at"],
            )
        )

    def random_template(self, risk_subcategory: str) -> StoredTemplate | None:
        row = (
            self.connection.execute(
                sa.select(attack_templates)
                .where(
                    attack_templates.c.risk_subcategory == risk_subcategory,
                )
                .order_by(sa.func.random())
                .limit(1)
            )
            .mappings()
            .first()
        )
        return (
            None
            if row is None
            else StoredTemplate(
                row["id"],
                AttackTemplate.model_validate(row["payload"]),
                row["created_at"],
            )
        )

    def get_attack(self, record_id: UUID) -> StoredAttack | None:
        row = (
            self.connection.execute(sa.select(attacks).where(attacks.c.id == record_id))
            .mappings()
            .first()
        )
        return None if row is None else self._attack(row)

    def list_attacks(
        self,
        *,
        subcategory: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[StoredAttack]:
        if not 1 <= limit <= 1000 or offset < 0:
            raise ValueError("limit must be 1..1000 and offset must be nonnegative")
        query = sa.select(attacks)
        if subcategory is not None:
            query = query.where(attacks.c.subcategory == subcategory)
        rows = self.connection.execute(
            query.order_by(
                attacks.c.created_at,
                attacks.c.id,
            )
            .limit(limit)
            .offset(offset)
        ).mappings()
        return [self._attack(row) for row in rows]

    @staticmethod
    def _attack(row) -> StoredAttack:
        return StoredAttack(
            row["id"],
            AttackData.model_validate(row["payload"]),
            row["source_template_id"],
            row["created_at"],
        )
