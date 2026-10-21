from app.llm.client import LLMError, LLMNotConfiguredError, get_llm_client
from app.main import app
from tests.conftest import FakeLLM

URL = "/api/v1/tickets/analyze"
TICKET = {
    "ticket_text": "El enlace hacia SITE-NORTE-01 está caído desde las 3 AM.",
    "logs": "rtr-norte-01 %LINK-3-UPDOWN: Interface TenGigE0/0/0/1, changed state to down",
}


def use_llm(llm):
    app.dependency_overrides[get_llm_client] = lambda: llm


def test_analyze_returns_classification_and_metadata(client):
    llm = FakeLLM()
    use_llm(llm)

    response = client.post(URL, json=TICKET)

    assert response.status_code == 200
    body = response.json()
    assert body["classification"]["category"] == "connectivity_loss"
    assert body["classification"]["severity"] == "critical"
    assert body["classification"]["entities"]["sites"] == ["SITE-NORTE-01"]
    assert body["model"] == "fake-model"
    assert body["reasoning_effort"] == "low"
    assert body["prompt_version"] == "classify_v1"
    assert body["usage"] == {
        "input_tokens": 1200,
        "output_tokens": 150,
        "reasoning_tokens": 40,
        "total_tokens": 1350,
    }


def test_analyze_sends_ticket_and_logs_inside_delimiters(client):
    llm = FakeLLM()
    use_llm(llm)

    client.post(URL, json=TICKET)

    last_message = llm.calls[0][-1]
    assert last_message["role"] == "user"
    assert f"<ticket>\n{TICKET['ticket_text']}\n</ticket>" in last_message["content"]
    assert f"<logs>\n{TICKET['logs']}\n</logs>" in last_message["content"]


def test_analyze_rejects_too_short_ticket(client):
    llm = FakeLLM()
    use_llm(llm)

    response = client.post(URL, json={"ticket_text": "caído"})

    assert response.status_code == 422
    assert llm.calls == []


def test_analyze_returns_502_when_llm_fails(client):
    use_llm(FakeLLM(error=LLMError("LLM refused the request: secret provider detail")))

    response = client.post(URL, json=TICKET)

    assert response.status_code == 502
    assert "secret provider detail" not in response.text


def test_analyze_returns_503_when_llm_not_configured(client):
    def not_configured():
        raise LLMNotConfiguredError("Set OPENAI_API_KEY and OPENAI_MODEL to enable analysis")

    app.dependency_overrides[get_llm_client] = not_configured

    response = client.post(URL, json=TICKET)

    assert response.status_code == 503
