class OperationError(Exception):
    def __init__(self, code: str, status: int = 422, details: list[dict] | None = None):
        super().__init__(code)
        self.code = code
        self.status = status
        self.details = details or []
