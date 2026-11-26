"""Run with python -m ai_judge.phase2.worker [--once]; no FastAPI server required."""

import argparse
import json
import sys
import time

import httpx
from pydantic import ValidationError

from ai_judge.config import Settings
from ai_judge.phase2.adapters import AdapterRegistry, OllamaAdapter
from ai_judge.phase2.runner import TargetRunner
from ai_judge.phase2.settings import TargetSettings
from ai_judge.storage.database import Database, StorageError, create_database_engine


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Block 2 persistent target-testing worker")
    parser.add_argument("--once", action="store_true", help="Claim at most one queued run and exit")
    parser.add_argument("--poll-seconds", type=float, default=2)
    args = parser.parse_args(argv)
    if not 0.1 <= args.poll_seconds <= 60:
        parser.error("--poll-seconds must be 0.1..60")
    database = None
    try:
        settings = TargetSettings()
        database = Database(create_database_engine(Settings()))
        with httpx.Client(follow_redirects=False, trust_env=False, timeout=30) as client:
            runner = TargetRunner(
                database, settings, AdapterRegistry({"ollama": OllamaAdapter(client)})
            )
            while True:
                processed = runner.run_once()
                if args.once or processed:
                    print(json.dumps({"processed": processed}))
                if args.once:
                    return 0
                if not processed:
                    time.sleep(args.poll_seconds)
    except ValidationError:
        print("worker_configuration_error", file=sys.stderr)
        return 2
    except StorageError:
        print("worker_storage_unavailable", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    finally:
        if database is not None:
            database.close()


if __name__ == "__main__":
    raise SystemExit(main())
