import json
from uuid import UUID

from pydantic import ValidationError

from ai_judge.contracts import AttackData, AttackTemplate
from ai_judge.phase1.errors import OperationError
from ai_judge.phase1.operations import Operations
from ai_judge.phase1.settings import Phase1Settings
from ai_judge.storage.repository import Repository


def strict_json(value: str):
    def invalid_constant(_):
        raise ValueError("non-finite JSON")

    def unique_keys(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = item
        return result

    return json.loads(value, parse_constant=invalid_constant, object_pairs_hook=unique_keys)


def validation_details(error: ValidationError, record: int) -> list[dict]:
    return [
        {"record": record, "path": list(item["loc"]), "type": item["type"]}
        for item in error.errors(include_input=False, include_context=False, include_url=False)
    ]


class Importer:
    def __init__(self, operations: Operations, settings: Phase1Settings):
        self.operations = operations
        self.settings = settings

    def attacks(self, raw: bytes, job_id: UUID | None = None) -> tuple[int, dict]:
        return self.operations.execute("attack_import", job_id, lambda jid: self._attacks(raw, jid))

    def templates(self, raw: bytes, job_id: UUID | None = None) -> tuple[int, dict]:
        return self.operations.execute(
            "template_import", job_id, lambda jid: self._templates(raw, jid)
        )

    def _templates(self, raw: bytes, job_id: UUID) -> dict:
        try:
            value = strict_json(raw.decode("utf-8-sig"))
        except UnicodeDecodeError:
            raise OperationError("invalid_utf8") from None
        except (ValueError, RecursionError):
            raise OperationError("invalid_json") from None
        values = value if isinstance(value, list) else [value]
        if not values or len(values) > self.settings.max_import_records:
            raise OperationError("invalid_record_count")
        records, errors = [], []
        for number, item in enumerate(values, 1):
            try:
                records.append(AttackTemplate.model_validate(item))
            except ValidationError as error:
                errors.extend(validation_details(error, number))
            if number % 100 == 0 or number == len(values):
                self.operations.progress(job_id, number, len(values))
        if errors:
            raise OperationError("invalid_records", details=errors)
        with self.operations.database.transaction() as connection:
            repo = Repository(connection)
            ids = repo.add_templates(records)
            result = {
                "imported": len(ids),
                "ids": [str(value) for value in ids],
                "duplicate_policy": "preserve",
            }
            repo.finish_job(job_id, "succeeded", result)
        return result

    def _attacks(self, raw: bytes, job_id: UUID) -> dict:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise OperationError("invalid_utf8") from None
        lines = text.splitlines()
        if not lines or len(lines) > self.settings.max_import_records:
            raise OperationError("invalid_record_count")
        records, errors = [], []
        for number, line in enumerate(lines, 1):
            try:
                records.append(AttackData.model_validate(strict_json(line)))
            except ValidationError as error:
                errors.extend(validation_details(error, number))
            except (ValueError, RecursionError):
                errors.append({"record": number, "path": [], "type": "invalid_json"})
            if number % 100 == 0 or number == len(lines):
                self.operations.progress(job_id, number, len(lines))
        if errors:
            raise OperationError("invalid_records", details=errors)
        with self.operations.database.transaction() as connection:
            repo = Repository(connection)
            ids = repo.add_attacks(records)
            result = {
                "imported": len(ids),
                "ids": [str(value) for value in ids],
                "duplicate_policy": "preserve",
            }
            repo.finish_job(job_id, "succeeded", result)
        return result
