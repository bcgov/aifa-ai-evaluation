from fastapi.testclient import TestClient

from promptfoo.src.promptfoo_adapter import app


client = TestClient(app)


def test_promptfoo_adapter_healthcheck():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_promptfoo_adapter_invoke(monkeypatch):
    class FakeWrapper:
        def __init__(self, *args, **kwargs):
            self.calls = []

        async def invoke(self, *, query: str, step_number: str | None = None):
            self.calls.append({"query": query, "step_number": step_number})
            return {"response_message": "The application fee is $100."}

        @staticmethod
        def extract_output(response):
            return response["response_message"]

        async def close(self):
            return None

    monkeypatch.setattr("promptfoo.src.promptfoo_adapter.PromptfooHttpWrapper", FakeWrapper)

    response = client.post(
        "/invoke",
        json={"query": "What is the application fee?", "step_number": "step2-Eligibility"},
    )

    assert response.status_code == 200
    assert response.json()["response_message"] == "The application fee is $100."
