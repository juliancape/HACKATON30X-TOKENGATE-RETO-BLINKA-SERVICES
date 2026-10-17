"""Servicio LLM con Gemini via REST (generativelanguage.googleapis.com).

Usa respuesta JSON estructurada para interpretar la solicitud del empleado
y redactar los mensajes de presentacion de opciones.
"""
from typing import Any

import httpx

from app.config import get_settings
from app.logging_setup import get_logger
from app.models.purchase import RequisitosCompra

log = get_logger(__name__)

PROMPT_REQUISITOS = """Eres un asistente de compras corporativas. El empleado escribe que desea \
comer/comprar y tu trabajo es extraer los requisitos de busqueda.
Devuelve JSON con la estructura:
{{"descripcion": str, "presupuesto_maximo_cop": int|null, "cantidad_personas": int, "restricciones": [str]}}
Reglas:
- presupuesto_maximo_cop es el maximo por pedido que el empleado menciona; null si no lo dice.
- restricciones incluye alergias, dietas, tipo de comida, ubicacion o tiempo maximo de entrega que mencione.
- No inventes datos que el empleado no dijo.
Solicitud del empleado: {solicitud}"""


class LlmError(Exception):
    """Error al invocar el modelo Gemini."""


class GeminiService:
    """Cliente minimalista de la API de Gemini con salida JSON estructurada."""

    def __init__(self) -> None:
        settings = get_settings()
        self._api_key = settings.gemini_api_key
        self._modelo = settings.gemini_model
        self._client = httpx.AsyncClient(timeout=60.0)

    async def close(self) -> None:
        await self._client.aclose()

    async def _generar_json(self, prompt: str) -> dict[str, Any]:
        """Ejecuta el prompt exigiendo salida JSON parseable."""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self._modelo}:generateContent"
        try:
            respuesta = await self._client.post(
                url,
                params={"key": self._api_key},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"response_mime_type": "application/json", "temperature": 0.2},
                },
            )
            respuesta.raise_for_status()
            datos = respuesta.json()
            texto = datos["candidates"][0]["content"]["parts"][0]["text"]
            import json

            return json.loads(texto)
        except httpx.HTTPStatusError as exc:
            log.error("gemini_http_error", status=exc.response.status_code)
            raise LlmError(f"Gemini respondio {exc.response.status_code}") from exc
        except (KeyError, ValueError, httpx.HTTPError) as exc:
            log.error("gemini_error", error=str(exc))
            raise LlmError("Respuesta invalida de Gemini") from exc

    async def extraer_requisitos(self, solicitud: str) -> RequisitosCompra:
        """Convierte la solicitud en lenguaje natural a requisitos estructurados."""
        datos = await self._generar_json(PROMPT_REQUISITOS.format(solicitud=solicitud))
        return RequisitosCompra.model_validate(datos)

    async def redactar_presentacion(self, solicitud: str, opciones: list[dict[str, Any]]) -> str:
        """Redacta el mensaje que presenta las opciones al empleado."""
        resumen = "\n".join(
            f"- {o.get('producto_nombre')} en {o.get('tienda_nombre')} por {o.get('precio_cop')} COP"
            for o in opciones
        )
        prompt = (
            "Redacta un mensaje corto de WhatsApp en espanol que presente estas opciones al empleado. "
            "Menciona nombre, tienda y precio de cada una. Sin inventar datos.\n"
            f"Solicitud original: {solicitud}\nOpciones:\n{resumen}"
        )
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self._modelo}:generateContent"
        try:
            respuesta = await self._client.post(
                url,
                params={"key": self._api_key},
                json={"contents": [{"parts": [{"text": prompt}]}]},
            )
            respuesta.raise_for_status()
            datos = respuesta.json()
            return datos["candidates"][0]["content"]["parts"][0]["text"]
        except (httpx.HTTPError, KeyError, IndexError) as exc:
            log.warning("gemini_redaccion_fallo", error=str(exc))
            # Fallback determinista: el flujo no se detiene por un fallo de redaccion
            return resumen
