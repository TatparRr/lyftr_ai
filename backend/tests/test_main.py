from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture
def client(monkeypatch, tmp_path):
	monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
	monkeypatch.setenv("LLM_API_KEYS", "test-key-one,test-key-two")
	monkeypatch.setenv("ENABLE_FAILURE_SIMULATION", "true")
	main.configured_keys.cache_clear()
	with main._CACHE_LOCK:
		main._CACHE.clear()
	with TestClient(main.app) as test_client:
		yield test_client
	main.configured_keys.cache_clear()


def fake_response(text="A test reply."):
	return SimpleNamespace(
		choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
		usage=SimpleNamespace(prompt_tokens=17, completion_tokens=4),
	)


def test_health_and_cache_hit_across_sessions(client, monkeypatch):
	calls = []

	def fake_completion(**kwargs):
		calls.append(kwargs)
		return fake_response()

	monkeypatch.setattr(main, "completion", fake_completion)
	assert client.get("/health").json() == {
		"status": "ok",
		"keys_configured": 2,
		"cache_enabled": True,
	}

	first = client.post("/chat", json={"session_id": "s-one", "message": "Hello"})
	second = client.post("/chat", json={"session_id": "s-two", "message": "Hello"})
	assert first.status_code == second.status_code == 200
	assert first.json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"
	assert second.json()["metadata"]["resolution_source"] == "LLM_CACHE"
	assert second.json()["reply"] == first.json()["reply"]
	assert second.json()["metadata"]["key_id"] is None
	assert second.json()["metadata"]["input_tokens"] == 17
	assert second.json()["metadata"]["output_tokens"] == 4
	assert len(calls) == 1


def test_simulated_failover_and_all_keys_unavailable(client, monkeypatch):
	calls = []

	def fake_completion(**kwargs):
		calls.append(kwargs["api_key"])
		return fake_response()

	monkeypatch.setattr(main, "completion", fake_completion)
	response = client.post(
		"/chat",
		json={"session_id": "failover", "message": "Try this"},
		headers={"X-Simulate-Failure": "key_1=429"},
	)
	assert response.status_code == 200
	assert response.json()["metadata"]["key_id"] == "key_2"
	assert response.json()["metadata"]["fallback_attempts"] == 1
	assert calls == ["test-key-two"]

	unavailable = client.post(
		"/chat",
		json={"session_id": "all-down", "message": "Do not save"},
		headers={"X-Simulate-Failure": "*=429"},
	)
	assert unavailable.status_code == 503
	assert unavailable.json() == {"detail": "all providers unavailable"}
	assert client.get("/sessions/all-down/messages").status_code == 404


def test_multi_turn_history_and_validation(client, monkeypatch):
	seen_messages = []

	def fake_completion(**kwargs):
		seen_messages.append(kwargs["messages"])
		return fake_response()

	monkeypatch.setattr(main, "completion", fake_completion)
	client.post("/chat", json={"session_id": "multi", "message": "First"})
	client.post("/chat", json={"session_id": "multi", "message": "Second"})
	assert [message["role"] for message in seen_messages[1]] == ["system", "user", "assistant", "user"]
	assert seen_messages[1][-1]["content"] == "Second"

	history = client.get("/sessions/multi/messages")
	assert history.status_code == 200
	messages = history.json()["messages"]
	assert [item["role"] for item in messages] == ["user", "assistant", "user", "assistant"]
	assert "metadata" in messages[1]
	assert client.post("/chat", json={"session_id": "multi", "message": "   "}).status_code == 422
	assert client.get("/sessions/unknown/messages").json() == {"detail": "session not found"}
