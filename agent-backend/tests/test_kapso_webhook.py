"""Pruebas del webhook de Kapso: firma HMAC e idempotencia."""
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.routers import kapso_webhook
from app.routers.kapso_webhook import verificar_firma


@pytest.fixture(autouse=True)
def secreto_webhook(monkeypatch):
    """Asegura un secreto configurado para todos los tests del webhook."""
    monkeypatch.setenv("KAPSO_WEBHOOK_SECRET", "secreto_test")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client() -> TestClient:
    from app.main import app

    return TestClient(app)


def payload_inbound() -> dict:
    return {
        "message": {
            "id": "wamid.1",
            "timestamp": "1730092800",
            "type": "text",
            "text": {"body": "quiero sushi"},
            "kapso": {"direction": "inbound", "status": "received", "content": "quiero sushi"},
        },
        "conversation": {"id": "conv_1", "phone_number": "573001112222"},
        "phone_number_id": "123",
    }


def test_firma_valida() -> None:
    cuerpo = b'{"hola": 1}'
    firma = hmac.new(b"secreto_test", cuerpo, hashlib.sha256).hexdigest()
    assert verificar_firma(cuerpo, firma) is True


def test_firma_invalida_rechaza() -> None:
    assert verificar_firma(b"{}", "abc") is False
    assert verificar_firma(b"{}", None) is False


def test_webhook_sin_firma_da_401(client: TestClient) -> None:
    respuesta = client.post("/webhooks/kapso", json=payload_inbound())
    assert respuesta.status_code == 401


def test_webhook_con_firma_responde_200_y_procesa(client: TestClient) -> None:
    kapso_webhook._procesados.clear()
    # Orquestador fake para no tocar servicios externos
    class FakeOrquestador:
        async def manejar_mensaje(self, *args, **kwargs):
            FakeOrquestador.llamado = True

    FakeOrquestador.llamado = False
    original = kapso_webhook.get_orquestador
    import app.services.orchestrator as orch

    orch._orquestador = FakeOrquestador()
    try:
        cuerpo = json.dumps(payload_inbound()).encode()
        firma = hmac.new(b"secreto_test", cuerpo, hashlib.sha256).hexdigest()
        respuesta = client.post(
            "/webhooks/kapso",
            content=cuerpo,
            headers={"X-Webhook-Signature": firma, "Content-Type": "application/json"},
        )
        assert respuesta.status_code == 200
        assert respuesta.json()["status"] == "recibido"
    finally:
        orch._orquestador = None


def test_webhook_mensaje_outbound_se_ignora(client: TestClient) -> None:
    kapso_webhook._procesados.clear()
    evento = payload_inbound()
    evento["message"]["kapso"]["direction"] = "outbound"
    cuerpo = json.dumps(evento).encode()
    firma = hmac.new(b"secreto_test", cuerpo, hashlib.sha256).hexdigest()
    respuesta = client.post(
        "/webhooks/kapso",
        content=cuerpo,
        headers={"X-Webhook-Signature": firma, "Content-Type": "application/json"},
    )
    assert respuesta.json()["status"] == "ignorado"
