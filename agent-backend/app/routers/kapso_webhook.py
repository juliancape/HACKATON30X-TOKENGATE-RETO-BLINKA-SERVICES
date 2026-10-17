"""Webhook de Kapso: verificacion HMAC, idempotencia y enrutado al orquestador."""
import asyncio
import hashlib
import hmac
import json

from fastapi import APIRouter, Header, HTTPException, Request

from app.config import get_settings
from app.logging_setup import get_logger
from app.models.kapso import KapsoWebhookPayload, extraer_contenido
from app.services.orchestrator import get_orquestador

log = get_logger(__name__)
router = APIRouter()

# Idempotencia simple en memoria para el MVP (Kapso puede reenviar eventos)
_procesados: set[str] = set()


def verificar_firma(raw_body: bytes, firma: str | None) -> bool:
    """HMAC SHA256 timing-safe contra el secreto del webhook."""
    secreto = get_settings().kapso_webhook_secret
    if not secreto:
        log.warning("webhook_secret_no_configurado")
        return False
    if not firma:
        return False
    esperada = hmac.new(secreto.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(firma, esperada)


@router.post("/webhooks/kapso")
async def kapso_webhook(
    request: Request,
    x_webhook_signature: str | None = Header(default=None),
    x_idempotency_key: str | None = Header(default=None),
) -> dict:
    """Recibe eventos de Kapso, verifica firma y procesa mensajes entrantes."""
    raw_body = await request.body()
    if not verificar_firma(raw_body, x_webhook_signature):
        raise HTTPException(status_code=401, detail="Firma invalida")

    if x_idempotency_key:
        if x_idempotency_key in _procesados:
            return {"status": "duplicado"}
        _procesados.add(x_idempotency_key)

    evento = json.loads(raw_body)
    # Solo procesamos mensajes entrantes del cliente
    if evento.get("message", {}).get("kapso", {}).get("direction") != "inbound":
        return {"status": "ignorado"}

    payload = KapsoWebhookPayload.model_validate(evento)
    contenido = extraer_contenido(payload.message)
    telefono = payload.conversation.phone_number or payload.message.kapso.get("from", "")

    orquestador = get_orquestador()
    asyncio.create_task(
        orquestador.manejar_mensaje(payload.conversation.id, telefono, contenido)
    )
    # Responder 200 rapido (<10s) y procesar en background
    return {"status": "recibido"}
