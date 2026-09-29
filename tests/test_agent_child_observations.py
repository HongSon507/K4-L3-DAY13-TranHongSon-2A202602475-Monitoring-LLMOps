from __future__ import annotations

from contextlib import contextmanager

from app import agent as agent_module
from app.prompt_management import ResolvedPrompt


class RecordingLangfuseClient:
    def __init__(self) -> None:
        self.span_updates: list[dict] = []
        self.generation_updates: list[dict] = []

    def update_current_span(self, **kwargs) -> None:
        self.span_updates.append(kwargs)

    def update_current_generation(self, **kwargs) -> None:
        self.generation_updates.append(kwargs)


@contextmanager
def _noop_attributes(**kwargs):
    yield


def _install_client(monkeypatch) -> RecordingLangfuseClient:
    client = RecordingLangfuseClient()
    monkeypatch.setattr(agent_module, "get_langfuse_client", lambda: client)
    monkeypatch.setattr(agent_module, "propagate_attributes", _noop_attributes)
    return client


def test_retrieval_observation_records_sanitized_query(monkeypatch) -> None:
    client = _install_client(monkeypatch)
    agent = agent_module.LabAgent()

    docs = agent._retrieve.__wrapped__(agent, "Refund for student@vinuni.edu.vn?")

    update = client.span_updates[-1]
    assert update["output"] == {"doc_count": len(docs)}
    assert "student@vinuni.edu.vn" not in update["input"]["query"]
    assert "[REDACTED_EMAIL]" in update["input"]["query"]
    assert update["metadata"]["domain_match"] is True


def test_generation_observation_records_model_usage_cost_and_prompt(monkeypatch) -> None:
    client = _install_client(monkeypatch)
    agent = agent_module.LabAgent()
    prompt = ResolvedPrompt(
        text="Feature=qa\nDocs=x\nQuestion=call me 0987654321",
        name="day13-chat",
        label="candidate",
        version="2",
        source="langfuse",
    )

    response = agent._generate.__wrapped__(agent, prompt)

    update = client.generation_updates[-1]
    assert update["model"] == agent.model
    assert update["usage_details"]["input"] == response.usage.input_tokens
    assert update["usage_details"]["output"] == response.usage.output_tokens
    assert update["cost_details"]["total"] == agent._estimate_cost(
        response.usage.input_tokens, response.usage.output_tokens
    )
    assert update["metadata"]["prompt_label"] == "candidate"
    assert update["metadata"]["prompt_version"] == "2"
    assert update["completion_start_time"] is not None
    assert "0987654321" not in update["input"]["prompt_preview"]
