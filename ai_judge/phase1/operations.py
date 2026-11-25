from collections.abc import Callable
from datetime import UTC, datetime
from time import monotonic
from uuid import UUID, uuid4

from ai_judge.phase1.errors import OperationError
from ai_judge.storage.database import Database, StorageError
from ai_judge.storage.repository import Repository


class Operations:
    """Bounded synchronous work, executed off the HTTP event loop.

    Clients may supply X-Job-ID before starting to query progress concurrently.
    A job ID is never executed twice, including failed or interrupted jobs.
    """

    def __init__(self, database: Database):
        self.database = database

    def execute(self, kind: str, job_id: UUID | None, work: Callable) -> tuple[int, dict]:
        job_id = job_id or uuid4()
        started = monotonic()
        try:
            with self.database.transaction() as connection:
                if not Repository(connection).start_job(job_id, kind):
                    return 409, {"job_id": str(job_id), "error": "job_id_exists"}
            status = 201
            try:
                result = work(job_id)
            except OperationError as error:
                status = error.status
                result = {"error": error.code, "details": error.details}
                with self.database.transaction() as connection:
                    Repository(connection).finish_job(job_id, "failed", result)
            # Successful work commits its data and job result in ONE transaction.
            with self.database.transaction() as connection:
                record = Repository(connection).get_job(job_id)
            return status, {
                "job_id": str(job_id),
                "status": record["status"],
                "elapsed_ms": round((monotonic() - started) * 1000),
                **result,
            }
        except StorageError:
            # Recoverable SQL errors can be recorded using a fresh transaction.
            try:
                with self.database.transaction() as connection:
                    Repository(connection).finish_job(
                        job_id, "failed", {"error": "storage_unavailable"}
                    )
            except StorageError:
                pass  # A full outage may prevent recording failure; deadline remains visible.
            return 503, {"job_id": str(job_id), "error": "storage_unavailable"}

    def progress(self, job_id: UUID, processed: int, total: int):
        with self.database.transaction() as connection:
            Repository(connection).update_job_progress(job_id, processed, total)

    def get(self, job_id: UUID) -> dict | None:
        with self.database.transaction() as connection:
            repo = Repository(connection)
            job = repo.get_job(job_id)
            if job and job["status"] == "running":
                deadline = job["expires_at"]
                if deadline.tzinfo is None:  # SQLite unit substitute
                    deadline = deadline.replace(tzinfo=UTC)
                if datetime.now(UTC) >= deadline:
                    repo.finish_job(job_id, "interrupted", {"error": "execution_deadline_exceeded"})
                    job = repo.get_job(job_id)
            return job
