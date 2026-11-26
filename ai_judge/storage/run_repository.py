from datetime import UTC, datetime, timedelta
from uuid import UUID

import sqlalchemy as sa

from ai_judge.phase2.contracts import TargetError
from ai_judge.storage.tables import target_cases, target_rounds, target_runs

LEASE_SECONDS = 300


class RunRepository:
    def __init__(self, connection: sa.Connection):
        self.connection = connection

    def enqueue(self, run_id: UUID, load_id: UUID, payload: dict) -> bool:
        if self.connection.dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        samples = payload["loaded"]["snapshot"]["samples"]
        created = self.connection.execute(
            insert(target_runs)
            .values(
                id=run_id,
                load_id=load_id,
                payload=payload,
                status="queued",
                total_cases=len(samples),
            )
            .on_conflict_do_nothing(index_elements=["id"])
            .returning(target_runs.c.id)
        ).scalar_one_or_none()
        if created is None:
            return False
        self.connection.execute(
            target_cases.insert(),
            [
                {
                    "run_id": run_id,
                    "case_id": UUID(item["id"]),
                    "position": index,
                    "attack": item["data"],
                    "status": "queued",
                    "total_rounds": len(item["data"]["attack_content"]),
                }
                for index, item in enumerate(samples)
            ],
        )
        return True

    def get(self, run_id: UUID) -> dict | None:
        row = (
            self.connection.execute(sa.select(target_runs).where(target_runs.c.id == run_id))
            .mappings()
            .first()
        )
        return dict(row) if row else None

    def claim(self, owner: UUID) -> dict | None:
        identifier = self.connection.execute(
            sa.select(target_runs.c.id)
            .where(
                target_runs.c.status == "queued",
            )
            .order_by(target_runs.c.created_at, target_runs.c.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        ).scalar_one_or_none()
        if identifier is None:
            return None
        claimed = self.connection.execute(
            target_runs.update()
            .where(
                target_runs.c.id == identifier,
                target_runs.c.status == "queued",
            )
            .values(
                status="running",
                owner=owner,
                lease_expires_at=datetime.now(UTC) + timedelta(seconds=LEASE_SECONDS),
            )
            .returning(target_runs.c.id)
        ).scalar_one_or_none()
        return self.get(claimed) if claimed else None

    def renew(self, run_id: UUID, owner: UUID):
        now = datetime.now(UTC)
        updated = self.connection.execute(
            target_runs.update()
            .where(
                target_runs.c.id == run_id,
                target_runs.c.status == "running",
                target_runs.c.owner == owner,
                target_runs.c.lease_expires_at > now,
            )
            .values(lease_expires_at=now + timedelta(seconds=LEASE_SECONDS))
        )
        if updated.rowcount != 1:
            raise TargetError("run_lease_lost", 409)

    def begin_round(
        self, run_id: UUID, owner: UUID, case_id: UUID, number: int, request: dict, attempts: int
    ):
        self.renew(run_id, owner)
        self.connection.execute(
            target_rounds.insert().values(
                run_id=run_id,
                case_id=case_id,
                round_number=number,
                request=request,
                status="running",
                attempts=attempts,
            )
        )
        self.connection.execute(
            target_cases.update()
            .where(
                target_cases.c.run_id == run_id,
                target_cases.c.case_id == case_id,
            )
            .values(status="running")
        )
        self.connection.execute(
            target_runs.update()
            .where(target_runs.c.id == run_id)
            .values(
                current_case_id=case_id,
                current_round=number,
            )
        )

    def finish_round(
        self,
        run_id: UUID,
        owner: UUID,
        case_id: UUID,
        number: int,
        *,
        status: str,
        elapsed_ms: float,
        response: dict | None = None,
        evidence: dict | None = None,
        error: str | None = None,
    ):
        self.renew(run_id, owner)
        changed = self.connection.execute(
            target_rounds.update()
            .where(
                target_rounds.c.run_id == run_id,
                target_rounds.c.case_id == case_id,
                target_rounds.c.round_number == number,
                target_rounds.c.status == "running",
            )
            .values(
                status=status,
                elapsed_ms=elapsed_ms,
                response=response,
                evidence=evidence,
                error=error,
                finished_at=datetime.now(UTC),
            )
        )
        if changed.rowcount != 1:
            raise TargetError("round_already_finished", 409)
        self.connection.execute(
            target_cases.update()
            .where(
                target_cases.c.run_id == run_id,
                target_cases.c.case_id == case_id,
            )
            .values(completed_rounds=target_cases.c.completed_rounds + 1)
        )

    def finish_case(self, run_id: UUID, owner: UUID, case_id: UUID, error: str | None):
        self.renew(run_id, owner)
        changed = self.connection.execute(
            target_cases.update()
            .where(
                target_cases.c.run_id == run_id,
                target_cases.c.case_id == case_id,
                target_cases.c.status.in_(["queued", "running"]),
            )
            .values(status="failed" if error else "succeeded", error=error)
        )
        if changed.rowcount != 1:
            raise TargetError("case_already_finished", 409)
        self.connection.execute(
            target_runs.update()
            .where(target_runs.c.id == run_id)
            .values(
                completed_cases=target_runs.c.completed_cases + 1,
                failed_cases=target_runs.c.failed_cases + int(error is not None),
            )
        )

    def finish_run(self, run_id: UUID, owner: UUID, error: str | None = None):
        self.renew(run_id, owner)
        run = self.get(run_id)
        if error:
            status = "failed"
            self.connection.execute(
                target_cases.update()
                .where(
                    target_cases.c.run_id == run_id,
                    target_cases.c.status.in_(["queued", "running"]),
                )
                .values(status="interrupted", error=error)
            )
            self.connection.execute(
                target_rounds.update()
                .where(
                    target_rounds.c.run_id == run_id,
                    target_rounds.c.status == "running",
                )
                .values(
                    status="interrupted",
                    error="inference_state_unknown",
                    finished_at=datetime.now(UTC),
                )
            )
        elif run["completed_cases"] != run["total_cases"]:
            raise TargetError("run_incomplete", 409)
        elif run["failed_cases"] == run["total_cases"]:
            status = "failed"
        elif run["failed_cases"]:
            status = "partial"
        else:
            status = "succeeded"
        self.connection.execute(
            target_runs.update()
            .where(target_runs.c.id == run_id)
            .values(
                status=status,
                error=error,
                finished_at=datetime.now(UTC),
                current_case_id=None,
                current_round=None,
            )
        )

    def reap_expired(self) -> list[UUID]:
        expired = list(
            self.connection.execute(
                target_runs.update()
                .where(
                    target_runs.c.status == "running",
                    target_runs.c.lease_expires_at <= datetime.now(UTC),
                )
                .values(
                    status="interrupted", error="worker_interrupted", finished_at=datetime.now(UTC)
                )
                .returning(target_runs.c.id)
            ).scalars()
        )
        if expired:
            self.connection.execute(
                target_cases.update()
                .where(
                    target_cases.c.run_id.in_(expired),
                    target_cases.c.status.in_(["queued", "running"]),
                )
                .values(status="interrupted", error="worker_interrupted")
            )
            self.connection.execute(
                target_rounds.update()
                .where(
                    target_rounds.c.run_id.in_(expired),
                    target_rounds.c.status == "running",
                )
                .values(
                    status="interrupted",
                    error="inference_state_unknown",
                    finished_at=datetime.now(UTC),
                )
            )
        return expired

    def list_cases(self, run_id: UUID, limit: int = 20, offset: int = 0) -> list[dict]:
        self._pagination(limit, offset)
        return [
            dict(row)
            for row in self.connection.execute(
                sa.select(target_cases)
                .where(
                    target_cases.c.run_id == run_id,
                )
                .order_by(target_cases.c.position)
                .limit(limit)
                .offset(offset)
            ).mappings()
        ]

    def list_rounds(
        self, run_id: UUID, case_id: UUID, limit: int = 20, offset: int = 0
    ) -> list[dict]:
        self._pagination(limit, offset)
        return [
            dict(row)
            for row in self.connection.execute(
                sa.select(target_rounds)
                .where(
                    target_rounds.c.run_id == run_id,
                    target_rounds.c.case_id == case_id,
                )
                .order_by(target_rounds.c.round_number)
                .limit(limit)
                .offset(offset)
            ).mappings()
        ]

    @staticmethod
    def _pagination(limit: int, offset: int):
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("limit must be 1..100; offset must be nonnegative")
