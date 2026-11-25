import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

from ai_judge.contracts import AttackData, AttackTemplate
from ai_judge.storage.database import Database
from ai_judge.storage.tables import metadata


@pytest.fixture
def attack():
    return AttackData(subcategory="synthetic", attack_content=["合成測試第一輪", "第二輪"])


@pytest.fixture
def template():
    return AttackTemplate(
        risk_subcategory="synthetic",
        environment="合成環境",
        power_relationship="測試角色",
        rounds=[dict(round=1, objective="測試格式", target_weakness="測試欄位")],
    )


@pytest.fixture
def database():
    # SQLite is a unit-test substitute only, never the production storage backend.
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    metadata.create_all(engine)
    yield Database(engine)
    engine.dispose()
