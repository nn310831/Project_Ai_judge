from fastapi.testclient import TestClient

from ai_judge.main import create_app


def test_target_routes_document_auth_success_and_errors(database):
    with TestClient(create_app(database)) as client:
        schema = client.get("/openapi.json").json()
    paths = {
        path: methods
        for path, methods in schema["paths"].items()
        if path.startswith("/api/v1/target-models/")
    }
    assert len(paths) == 7
    for methods in paths.values():
        for operation in methods.values():
            assert operation["security"] == [{"HTTPBearer": []}]
            assert {"401", "403", "404", "409", "422", "503"} <= operation["responses"].keys()
    accepted = paths["/api/v1/target-models/test/ollama"]["post"]["responses"]["202"]
    assert accepted["content"]["application/json"]["schema"]["$ref"].endswith("/AcceptedRun")
    fields = schema["components"]["schemas"]["TestRequest"]["properties"]
    assert fields["sliding_window"]["default"] is False
    assert fields["use_mock"]["default"] is False
