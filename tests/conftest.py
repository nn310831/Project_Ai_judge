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


@pytest.fixture
def target_setup(database, attack):
    from ai_judge.phase2.adapters import AdapterRegistry
    from ai_judge.phase2.configuration import ConfigurationService
    from ai_judge.phase2.contracts import TargetConfig
    from ai_judge.phase2.loading import LoadingService, Sample, SamplingSnapshot
    from ai_judge.phase2.settings import TargetSettings
    from ai_judge.storage.repository import Repository

    settings = TargetSettings(_env_file=None, api_token="test-only-token", mock_enabled=True)
    registry = AdapterRegistry({"ollama": object()})  # Loading never invokes inference.
    config_id = ConfigurationService(database, settings).create(
        TargetConfig(
            base_url="http://127.0.0.1:11434",
            model="synthetic-test-model",
        )
    )
    with database.transaction() as connection:
        attack_id = Repository(connection).add_attacks([attack])[0]
    snapshot = SamplingSnapshot(samples=[Sample(id=attack_id, data=attack)], sampling={"k": 1})
    load_id = LoadingService(database, settings, registry).load_snapshot(config_id, snapshot)
    return load_id, settings, registry, attack_id, config_id
