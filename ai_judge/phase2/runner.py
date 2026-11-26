"""B2-3 multi-turn runner. Model calls never occur inside database transactions."""

from time import monotonic
from uuid import UUID, uuid4

from ai_judge.contracts import ModelOutput
from ai_judge.phase2.adapters import AdapterRegistry, TargetReply
from ai_judge.phase2.configuration import ConfigurationService
from ai_judge.phase2.context import ConversationContext
from ai_judge.phase2.contracts import TargetConfig, TargetError
from ai_judge.phase2.loading import LoadedTarget, Sample
from ai_judge.phase2.normalization import normalize_reply
from ai_judge.phase2.reasoning import build_judging_input
from ai_judge.phase2.settings import TargetSettings
from ai_judge.storage.database import Database, StorageError
from ai_judge.storage.run_repository import RunRepository


# 模擬受測模型：預設不啟用。必須同時開啟本機 mock_enabled 與本次 use_mock。
# Placed in the upper part of this module as required; never a real-call fallback.
class MockTargetAdapter:
    def chat(self, config: TargetConfig, messages: list[dict[str, str]]) -> TargetReply:
        output = ModelOutput(
            situation="Synthetic mock evaluation",
            query=messages[-1]["content"],
            reasoning_steps=["Synthetic public explanation; not real model reasoning."],
            final_response="Synthetic mock response.",
        )
        return TargetReply(
            output.model_dump_json(),
            config.provider,
            config.model,
            mock=True,
            metadata={"simulation": "target-mock-v1"},
        )


class TargetRunner:
    def __init__(self, database: Database, settings: TargetSettings, registry: AdapterRegistry):
        self.database, self.settings, self.registry = database, settings, registry

    def run_once(self) -> bool:
        owner = uuid4()
        with self.database.transaction() as connection:
            repo = RunRepository(connection)
            repo.reap_expired()
            run = repo.claim(owner)
        if run is None:
            return False
        self.run_claimed(run["id"], owner)
        return True

    def run_claimed(self, run_id: UUID, owner: UUID):
        try:
            with self.database.transaction() as connection:
                repo = RunRepository(connection)
                repo.renew(run_id, owner)
                run = repo.get(run_id)
            payload = run["payload"]
            loaded = LoadedTarget.model_validate(payload["loaded"])
            config = loaded.configuration
            ConfigurationService(self.database, self.settings).validate_endpoint(config)
            if payload["mock"]:
                if not self.settings.mock_enabled:
                    raise TargetError("target_mock_not_enabled", 403)
                adapter = MockTargetAdapter()
            else:
                adapter = self.registry.resolve(config.provider)
            for sample in loaded.snapshot.samples:
                self.run_case(
                    run_id,
                    owner,
                    sample,
                    config,
                    payload["sliding_window"],
                    payload["mock"],
                    adapter,
                )
            with self.database.transaction() as connection:
                RunRepository(connection).finish_run(run_id, owner)
        except TargetError as error:
            if error.code == "run_lease_lost":
                return  # A stale worker must never overwrite another terminal state.
            self._abort(run_id, owner, error.code)
        except StorageError:
            # Leave an uncertain invocation for lease recovery, never retry inference.
            raise
        except Exception:
            self._abort(run_id, owner, "internal_worker_error")

    def _abort(self, run_id: UUID, owner: UUID, code: str):
        with self.database.transaction() as connection:
            RunRepository(connection).finish_run(run_id, owner, error=code)

    def run_case(
        self,
        run_id: UUID,
        owner: UUID,
        sample: Sample,
        config: TargetConfig,
        sliding_window: bool,
        mock: bool,
        adapter,
    ):
        context = ConversationContext(
            sliding_window=sliding_window,
            window_turns=config.window_turns,
            max_characters=config.context_max_characters,
        )
        case_error = None
        for number, query in enumerate(sample.data.attack_content, 1):
            started = monotonic()
            request = {
                "query": query,
                "provider": config.provider,
                "model": config.model,
                "parameters": config.parameters.model_dump(),
                "timeout_seconds": config.timeout_seconds,
                "sliding_window": sliding_window,
                "mock": mock,
                "messages": [],
            }
            attempts, error, status = 0, case_error, "skipped" if case_error else "failed"
            if not case_error:
                try:
                    prepared = context.prepare(query)
                    request.update(
                        messages=prepared.messages,
                        dropped_turns=prepared.dropped_turns,
                        context_characters=prepared.context_characters,
                    )
                    attempts = 1
                except TargetError as failure:
                    error = failure.code
            with self.database.transaction() as connection:
                RunRepository(connection).begin_round(
                    run_id, owner, sample.id, number, request, attempts
                )
            response, evidence, normalized = None, None, None
            if attempts:
                try:
                    reply = adapter.chat(config, request["messages"])
                    if not isinstance(reply, TargetReply):
                        raise TargetError("invalid_target_reply", 502)
                    response = {
                        "content": reply.content,
                        "provider": reply.provider,
                        "model": reply.model,
                        "mock": reply.mock,
                        "metadata": reply.metadata,
                    }
                    if reply.provider != config.provider or reply.mock != mock:
                        raise TargetError("target_source_mismatch", 502)
                    normalized = normalize_reply(reply)
                    evidence = build_judging_input(
                        normalized, run_id, sample.id, number
                    ).as_path_input()
                    response["output"] = normalized.output.model_dump()
                    status = "succeeded"
                except TargetError as failure:
                    error = failure.code
                except Exception:
                    error = "target_internal_error"
            if error:
                case_error = error
            with self.database.transaction() as connection:
                RunRepository(connection).finish_round(
                    run_id,
                    owner,
                    sample.id,
                    number,
                    status=status,
                    elapsed_ms=round((monotonic() - started) * 1000, 3),
                    response=response,
                    evidence=evidence,
                    error=error,
                )
            if status == "succeeded":
                context.complete(query, normalized.output.model_dump_json())
        with self.database.transaction() as connection:
            RunRepository(connection).finish_case(run_id, owner, sample.id, case_error)
