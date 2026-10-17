"""Cliente REST de Kapso (WhatsApp Cloud API proxied) para enviar mensajes."""
from typing import Any

import httpx

from app.config import get_settings
from app.logging_setup import get_logger

log = get_logger(__name__)


class KapsoError(Exception):
    """Error al comunicarse con la API de Kapso."""


class KapsoClient:
    """Envio de mensajes de texto y botones interactivos por WhatsApp."""

    def __init__(self) -> None:
        settings = get_settings()
        self._base_url = settings.kapso_base_url.rstrip("/")
        self._phone_number_id = settings.kapso_phone_number_id
        self._headers = {
            "X-API-Key": settings.kapso_api_key,
            "Content-Type": "application/json",
        }
        self._client = httpx.AsyncClient(timeout=30.0)

    async def close(self) -> None:
        await self._client.aclose()

    def _url_mensajes(self) -> str:
        return f"{self._base_url}/v24.0/{self._phone_number_id}/messages"

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST a la API de mensajes con manejo de errores."""
        try:
            respuesta = await self._client.post(self._url_mensajes(), headers=self._headers, json=payload)
            respuesta.raise_for_status()
            return respuesta.json()
        except httpx.HTTPStatusError as exc:
            log.error("kapso_http_error", status=exc.response.status_code, cuerpo=exc.response.text[:500])
            raise KapsoError(f"Kapso respondio {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            log.error("kapso_red_error", error=str(exc))
            raise KapsoError("No se pudo contactar a Kapso") from exc

    async def enviar_texto(self, telefono: str, texto: str) -> dict[str, Any]:
        """Envia un mensaje de texto simple."""
        return await self._post(
            {
                "messaging_product": "whatsapp",
                "to": telefono,
                "type": "text",
                "text": {"body": texto},
            }
        )

    async def enviar_botones(self, telefono: str, cuerpo: str, botones: list[dict[str, str]]) -> dict[str, Any]:
        """Envia hasta 3 botones de respuesta rapida ({id, titulo})."""
        if not 1 <= len(botones) <= 3:
            raise ValueError("WhatsApp permite entre 1 y 3 botones")
        return await self._post(
            {
                "messaging_product": "whatsapp",
                "to": telefono,
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": cuerpo},
                    "action": {
                        "buttons": [
                            {"type": "reply", "reply": {"id": b["id"], "title": b["titulo"]}} for b in botones
                        ]
                    },
                },
            }
        )

    async def enviar_lista(self, telefono: str, cuerpo: str, filas: list[dict[str, str]]) -> dict[str, Any]:
        """Envia una lista interactiva: filas con {id, titulo, descripcion}.

        Limites de WhatsApp: titulo de fila <= 24 chars, descripcion <= 72,
        cuerpo <= 1024, titulo de seccion <= 24, boton <= 20, max 10 filas.
        """
        filas_sanitizadas = [
            {
                "id": f["id"][:256],
                "title": f["titulo"][:24],
                "description": f.get("descripcion", "")[:72],
            }
            for f in filas[:10]
        ]
        return await self._post(
            {
                "messaging_product": "whatsapp",
                "to": telefono,
                "type": "interactive",
                "interactive": {
                    "type": "list",
                    "body": {"text": cuerpo[:1024]},
                    "action": {
                        "button": "Ver opciones"[:20],
                        "sections": [{"title": "Opciones"[:24], "rows": filas_sanitizadas}],
                    },
                },
            }
        )

    async def enviar_flow(self, telefono: str, flow_id: str, cuerpo: str, cta: str, datos: dict | None = None) -> dict[str, Any]:
        """Envia un WhatsApp Flow (formulario nativo) navegable a una pantalla.

        Requiere un Flow publicado en Meta (numero de produccion). Los `datos`
        prellenan los campos de la pantalla destino.
        """
        payload: dict[str, Any] = {
            "flow_message_version": "3",
            "flow_id": flow_id,
            "flow_cta": cta,
            "flow_action": "navigate",
        }
        action_payload: dict[str, Any] = {"screen": "REQUISITOS"}
        if datos:
            action_payload["data"] = datos
        payload["flow_action_payload"] = action_payload
        return await self._post(
            {
                "messaging_product": "whatsapp",
                "to": telefono,
                "type": "interactive",
                "interactive": {"type": "flow", "body": {"text": cuerpo}, "action": {"name": "flow", "parameters": payload}},
            }
        )
