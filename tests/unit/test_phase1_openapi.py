from fastapi.testclient import TestClient

from ai_judge.main import create_app


def test_public_operations_have_resolvable_response_schemas(database):
    with TestClient(create_app(database)) as client:
        schema = client.get("/openapi.json").json()
    expected = {
        "/api/v1/attacks/import": "ImportResult",
        "/api/v1/attack-templates/import": "ImportResult",
        "/api/v1/attacks/generate": "GenerationResult",
        "/api/v1/attacks/sample": "SamplingResult",
    }
    for path, model in expected.items():
        response = schema["paths"][path]["post"]["responses"]["201"]
        assert response["content"]["application/json"]["schema"]["$ref"].endswith("/" + model)

    def visit(value):
        if isinstance(value, dict):
            if "$ref" in value:
                assert value["$ref"].startswith("#/components/schemas/")
                assert value["$ref"].split("/")[-1] in schema["components"]["schemas"]
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(schema)
