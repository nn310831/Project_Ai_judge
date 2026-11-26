from ai_judge.phase2 import worker


def test_worker_once_uses_internal_runner_without_fastapi(database, monkeypatch, capsys):
    calls = []

    class Runner:
        def __init__(self, *args):
            calls.append("constructed")

        def run_once(self):
            calls.append("run_once")
            return False

    monkeypatch.setattr(worker, "Settings", lambda: None)
    monkeypatch.setattr(worker, "create_database_engine", lambda _: database.engine)
    monkeypatch.setattr(worker, "TargetRunner", Runner)
    assert worker.main(["--once"]) == 0
    assert calls == ["constructed", "run_once"]
    assert '"processed": false' in capsys.readouterr().out
