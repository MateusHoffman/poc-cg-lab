import json

from fastapi.testclient import TestClient

from app.main import create_app
from app.runtime import Runtime


def _stream(client: TestClient, query: str, session_id: str) -> str:
    with client.stream(
        "POST",
        "/api/chat",
        json={"query": query, "session_id": session_id},
    ) as response:
        assert response.status_code == 200
        return "".join(response.iter_text())


def test_chat_streams_vehicle_card_and_persists_session():
    app = create_app(Runtime.local())
    with TestClient(app) as client:
        raw = _stream(client, "Quero um Polo 2024", "api-1")
        assert "event: ui" in raw
        assert "Polo" in raw
        assert "event: metrics" in raw
        assert "http.chat" in raw
        assert "tool.vector_search" in raw
        session = client.get("/api/sessions/api-1").json()
        roles = [item["role"] for item in session["items"] if item.get("entity") == "message"]
        assert roles == ["user", "assistant"]
        state = next(item for item in session["items"] if item["SK"] == "STATE")
        assert "polo-2024" in state["vehicle_ids"]


def test_pii_never_reaches_the_session_store():
    app = create_app(Runtime.local())
    with TestClient(app) as client:
        raw = _stream(
            client,
            "Meu email é ana@example.com e quero um Onix",
            "api-pii",
        )
        assert "[EMAIL PROTEGIDO]" in raw
        assert '"texto_enviado_ao_modelo": "Meu email é [EMAIL PROTEGIDO] e quero um Onix"' in raw
        stored = json.dumps(client.get("/api/sessions/api-pii").json())
        assert "ana@example.com" not in stored


def test_repeated_query_hits_the_cache():
    app = create_app(Runtime.local())
    with TestClient(app) as client:
        _stream(client, "Quero um Polo", "cache-a")
        second = _stream(client, "Quero um Polo", "cache-b")
        assert '"cache_hit": true' in second


def test_health_lists_the_two_models_and_unknown_stays_offline():
    app = create_app(Runtime.local())
    with TestClient(app) as client:
        health = client.get("/api/health").json()
        assert health["models"] == ["offline-template", "llama3.1:8b"]
        with client.stream(
            "POST",
            "/api/chat",
            json={"query": "Quero um Polo", "session_id": "model-x", "model": "gpt-4o"},
        ) as response:
            raw = "".join(response.iter_text())
        assert '"model": "offline-template"' in raw


def test_ollama_stream_reads_message_chunks(monkeypatch):
    lines = [
        b'{"message":{"content":"Ola"},"done":false}\n',
        b'{"message":{"content":" Polo"},"done":true}\n',
    ]

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            return iter(lines)

    monkeypatch.setattr("app.llm.urllib.request.urlopen", lambda *_args, **_kwargs: FakeResponse())
    from app.llm import iter_completion

    assert "".join(iter_completion("sistema", "pergunta", "llama3.1:8b")) == "Ola Polo"


def test_llama_selection_streams_that_model(monkeypatch):
    def fake(_system: str, _user: str, model: str):
        assert model == "llama3.1:8b"
        yield "O Polo 2024 está no estoque."

    monkeypatch.setattr("app.main.iter_completion", fake)
    app = create_app(Runtime.local())
    with TestClient(app) as client:
        with client.stream(
            "POST",
            "/api/chat",
            json={"query": "Quero um Polo", "session_id": "model-llama", "model": "llama3.1:8b"},
        ) as response:
            raw = "".join(response.iter_text())
        assert "O Polo 2024 está no estoque." in raw
        assert '"model": "llama3.1:8b"' in raw


def test_feature_flag_disables_sandbox():
    app = create_app(Runtime.local())
    with TestClient(app) as client:
        updated = client.post("/api/flags/finance-sandbox", json={"enabled": False})
        assert updated.json()["finance-sandbox"] is False
        raw = _stream(client, "Simule o Polo em 48x", "api-flag")
        assert "desligada" in raw
        assert '"sandbox_used": false' in raw
