import json

from app.llm.client import LLMError, LLMNotConfiguredError, get_llm_client
from app.main import app
from app.schemas import TicketClassification, TicketDiagnosis
from tests.conftest import SAMPLE_CLASSIFICATION, FakeLLM

URL = "/api/v1/tickets/analyze"
TICKET = {
    "ticket_text": "El enlace hacia SITE-NORTE-01 está caído desde las 3 AM.",
    "logs": "rtr-norte-01 %LINK-3-UPDOWN: Interface TenGigE0/0/0/1, changed state to down",
}
CALLS_PER_ANALYSIS = 2  # classify, then diagnose


def use_llm(llm):
    app.dependency_overrides[get_llm_client] = lambda: llm


def test_analyze_stores_and_returns_the_analysis(db_client):
    use_llm(FakeLLM())

    response = db_client.post(URL, json=TICKET)

    assert response.status_code == 201
    body = response.json()
    assert body["cached"] is False
    assert body["classification"]["category"] == "connectivity_loss"
    assert body["classification"]["entities"]["sites"] == ["SITE-NORTE-01"]
    assert body["diagnosis"]["probable_causes"][0]["cause"] == "Fiber cut"
    assert body["diagnosis"]["customer_reply"].startswith("Estamos trabajando")
    assert body["ticket_text"] == TICKET["ticket_text"]
    assert body["model"] == "fake-model"
    assert body["reasoning_effort"] == "low"
    assert body["prompt_version"] == "classify_v2+diagnose_v1"

    stored = db_client.get(f"/api/v1/tickets/{body['id']}")
    assert stored.status_code == 200
    assert stored.json() == {k: v for k, v in body.items() if k != "cached"}


def test_usage_adds_up_both_calls(db_client):
    use_llm(FakeLLM())

    usage = db_client.post(URL, json=TICKET).json()["usage"]

    assert usage == {
        "input_tokens": 2400,
        "output_tokens": 300,
        "reasoning_tokens": 80,
        "total_tokens": 2700,
    }


def test_diagnosis_call_receives_the_classification(db_client):
    questions = ["¿Desde qué hora?"]
    custom = {**SAMPLE_CLASSIFICATION, "severity": "major", "missing_information": questions}
    llm = FakeLLM(outputs={TicketClassification: custom})
    use_llm(llm)

    db_client.post(URL, json=TICKET)

    assert llm.output_models == [TicketClassification, TicketDiagnosis]
    diagnose_input = llm.calls[1][-1]["content"]
    assert f"<ticket>\n{TICKET['ticket_text']}\n</ticket>" in diagnose_input
    block = diagnose_input.split("<classification>\n")[1].split("\n</classification>")[0]
    assert json.loads(block)["severity"] == "major"
    assert json.loads(block)["missing_information"] == questions


def test_identical_ticket_is_served_from_cache(db_client):
    llm = FakeLLM()
    use_llm(llm)

    first = db_client.post(URL, json=TICKET)
    second = db_client.post(URL, json=TICKET)

    assert second.status_code == 200
    assert second.json()["cached"] is True
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["diagnosis"] == first.json()["diagnosis"]
    assert len(llm.calls) == CALLS_PER_ANALYSIS


def test_cache_ignores_line_endings_and_edge_whitespace(db_client):
    llm = FakeLLM()
    use_llm(llm)

    db_client.post(URL, json=TICKET)
    variant = {
        "ticket_text": f"  {TICKET['ticket_text']}  \r\n",
        "logs": TICKET["logs"].replace("\n", "\r\n") + "\n",
    }
    response = db_client.post(URL, json=variant)

    assert response.json()["cached"] is True
    assert len(llm.calls) == CALLS_PER_ANALYSIS


def test_same_ticket_with_different_logs_is_analyzed_again(db_client):
    llm = FakeLLM()
    use_llm(llm)

    db_client.post(URL, json=TICKET)
    response = db_client.post(URL, json={**TICKET, "logs": "BFD session to 10.20.0.2 down"})

    assert response.status_code == 201
    assert len(llm.calls) == 2 * CALLS_PER_ANALYSIS


def test_analyze_sends_ticket_and_logs_inside_delimiters(db_client):
    llm = FakeLLM()
    use_llm(llm)

    db_client.post(URL, json=TICKET)

    last_message = llm.calls[0][-1]
    assert last_message["role"] == "user"
    assert f"<ticket>\n{TICKET['ticket_text']}\n</ticket>" in last_message["content"]
    assert f"<logs>\n{TICKET['logs']}\n</logs>" in last_message["content"]


def test_analyze_rejects_too_short_ticket(db_client):
    llm = FakeLLM()
    use_llm(llm)

    response = db_client.post(URL, json={"ticket_text": "caído"})

    assert response.status_code == 422
    assert llm.calls == []


def test_failed_classification_returns_502_and_stores_nothing(db_client):
    llm = FakeLLM(error=LLMError("LLM refused the request: secret provider detail"))
    use_llm(llm)

    response = db_client.post(URL, json=TICKET)

    assert response.status_code == 502
    assert "secret provider detail" not in response.text
    assert len(llm.calls) == 1  # the diagnosis is not attempted
    assert db_client.get("/api/v1/tickets").json()["total"] == 0


def test_failed_diagnosis_returns_502_and_stores_nothing(db_client):
    use_llm(FakeLLM(error=LLMError("LLM response incomplete"), fail_on=TicketDiagnosis))

    response = db_client.post(URL, json=TICKET)

    assert response.status_code == 502
    # A half analysis isn't stored: it would be served from the cache without a diagnosis.
    assert db_client.get("/api/v1/tickets").json()["total"] == 0


def test_analyze_returns_503_when_llm_not_configured(db_client):
    def not_configured():
        raise LLMNotConfiguredError("Set OPENAI_API_KEY and OPENAI_MODEL to enable analysis")

    app.dependency_overrides[get_llm_client] = not_configured

    response = db_client.post(URL, json=TICKET)

    assert response.status_code == 503
