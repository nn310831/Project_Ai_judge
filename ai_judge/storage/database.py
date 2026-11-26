from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Connection, Engine, create_engine
from sqlalchemy.exc import SQLAlchemyError

from ai_judge.config import Settings


class StorageError(Exception):
    """Safe public error; do not expose SQL, credentials or evaluated content."""


def create_database_engine(settings: Settings) -> Engine:
    return create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        hide_parameters=True,
        connect_args={
            "connect_timeout": settings.db_connect_timeout,
            "options": f"-c statement_timeout={settings.db_statement_timeout_ms}",
        },
    )


class Database:
    def __init__(self, engine: Engine):
        self.engine = engine

    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        """Commit only on successful exit; all exceptions roll back the whole unit."""
        try:
            with self.engine.begin() as connection:
                yield connection
        except SQLAlchemyError:
            raise StorageError("Database operation failed") from None

    def close(self) -> None:
        self.engine.dispose()
