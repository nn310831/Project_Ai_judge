from alembic import context

from ai_judge.config import Settings
from ai_judge.storage.database import create_database_engine
from ai_judge.storage.tables import metadata

if context.is_offline_mode():
    context.configure(
        url="postgresql+psycopg://",
        target_metadata=metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()
elif context.config.attributes.get("connection") is not None:
    context.configure(connection=context.config.attributes["connection"], target_metadata=metadata)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_database_engine(Settings())
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()
