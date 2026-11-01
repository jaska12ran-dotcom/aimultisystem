import asyncio

from intelligence.llm_client import LLMClient


def test_hf_provider_uses_explicit_api_key():
    client = LLMClient(provider="huggingface", api_key="hf-secret")
    assert client.provider == "huggingface"
    assert client.hf_api_key == "hf-secret"
    assert client.api_key == "hf-secret"


def test_hf_generate_sends_bearer_token():
    client = LLMClient(provider="huggingface", api_key="hf-secret", model="test-model")
    captured = {}

    class DummyResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    class DummyClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return DummyResponse()

    import intelligence.llm_client as llm_module

    original_client = llm_module.httpx.AsyncClient
    llm_module.httpx.AsyncClient = DummyClient
    try:
        async def run_generate():
            return await client._generate_huggingface("system", "user", 128, 0.2)

        result = asyncio.run(run_generate())
    finally:
        llm_module.httpx.AsyncClient = original_client

    assert result == "ok"
    assert captured["headers"]["Authorization"] == "Bearer hf-secret"
    assert captured["json"]["model"] == "test-model"
