import json
import time

import httpx
import pytest
from openai import OpenAI

from app.chat.schemas import ContextBundle
from app.core.errors import DomainError
from app.providers.openai_generation import OpenAIGenerationProvider


def response_payload(draft, status="completed", refusal=False):
    content = (
        [{"type": "refusal", "refusal": "Refused"}]
        if refusal
        else [{"type": "output_text", "text": json.dumps(draft), "annotations": []}]
    )
    return {
        "id": "resp_mock",
        "object": "response",
        "created_at": 1,
        "status": status,
        "model": "gpt-4.1-mini",
        "output": [
            {
                "id": "msg_mock",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": content,
            }
        ],
        "usage": {
            "input_tokens": 20,
            "output_tokens": 10,
            "total_tokens": 30,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
        "incomplete_details": {"reason": "max_output_tokens"} if status == "incomplete" else None,
    }


def make_provider(monkeypatch, handler):
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4.1-mini")
    client = OpenAI(
        api_key="local-test-only",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    return OpenAIGenerationProvider(client=client)


def test_openai_payload_is_bounded_and_store_false(monkeypatch):
    def handler(request):
        body = json.loads(request.content)
        assert body["store"] is False
        assert body["text"]["format"]["strict"] is True
        assert "tools" not in body and "previous_response_id" not in body
        return httpx.Response(
            200,
            json=response_payload(
                {"status": "insufficient_evidence", "clarification_question": None, "claims": []}
            ),
        )

    provider = make_provider(monkeypatch, handler)
    draft = provider.generate("Q", ContextBundle(), [], time.monotonic() + 60)
    assert draft.status == "insufficient_evidence"
    assert provider.metrics[0]["usage"]["total_tokens"] == 30


@pytest.mark.parametrize(
    "status,refusal,code",
    [("incomplete", False, "PROVIDER_INCOMPLETE"), ("completed", True, "PROVIDER_REFUSAL")],
)
def test_provider_refusal_and_incomplete(monkeypatch, status, refusal, code):
    provider = make_provider(
        monkeypatch, lambda r: httpx.Response(200, json=response_payload({}, status, refusal))
    )
    with pytest.raises(DomainError) as error:
        provider.generate("Q", ContextBundle(), [], time.monotonic() + 5)
    assert error.value.code == code


@pytest.mark.parametrize("status,want_calls", [(401, 1), (429, 2), (500, 2)])
def test_transport_retry_deadline(monkeypatch, status, want_calls):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status, headers={"Retry-After": "0"}, json={"error": {"message": "secret"}}
        )

    provider = make_provider(monkeypatch, handler)
    with pytest.raises(DomainError) as error:
        provider.generate("Q", ContextBundle(), [], time.monotonic() + 5)
    assert len(calls) == want_calls
    assert "secret" not in str(error.value)
