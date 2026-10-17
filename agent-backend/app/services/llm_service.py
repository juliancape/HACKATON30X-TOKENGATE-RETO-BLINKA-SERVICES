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

PROMPT_REQUISITOS = """Eres el agente de compras corporativas por WhatsApp. Clasifica el mensaje del empleado \
y extrae los requisitos de compra.

Devuelve JSON con la estructura:
{{"intencion": "saludo"|"compra"|"otro", "descripcion": str|null, "presupuesto_maximo_cop": int|null, \
"cantidad_personas": int|null, "restricciones": [str]}}
Reglas:
- "saludo": solo saluda, no pide nada concreto (ej: "hola", "buenas", "que tal").
- "compra": menciona algo que quiere pedir (aunque falten datos).
- "otro": pregunta del agente, queja u off-topic.
- descripcion: que desea comprar; null si es saludo u otro.
- presupuesto_maximo_cop: maximo por pedido que menciona; null si no lo dice.
- cantidad_personas: null si no lo dice.
- No inventes datos que el empleado no dijo.

Contexto previo de la conversacion (el empleado ya dijo esto, no lo pidas de nuevo): {previos}
Mensaje actual del empleado: {solicitud}"""


class LlmError(Exception):
    """Error al invocar el modelo Gemini."""


class GeminiService:
    """Cliente minimalista de la API de Gemini con salida JSON estructurada."""

    def __init__(self) -> None:
        settings = get_settings()
        self._api_key = settings.gemini_api_key
        self._modelo = settings.gemini_model
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, read=120.0))

    async def close(self) -> None:
        await self._client.aclose()

    async def _generar_json(self, prompt: str, max_intentos: int = 3) -> dict[str, Any]:
        """Ejecuta el prompt exigiendo salida JSON parseable, con reintentos ante 429."""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self._modelo}:generateContent"
        cuerpo = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.2,
                # gemini-3.8-flash es modelo con thinking; sin presupuesto 0 pasa de 60s
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }
        ultimo_error: Exception | None = None
        for intento in range(1, max_intentos + 1):
            try:
                respuesta = await self._client.post(url, params={"key": self._api_key}, json=cuerpo)
                if respuesta.status_code == 429:
                    # Rate limit del free tier: esperar y reintentar con backoff
                    espera = int(respuesta.headers.get("retry-after", "0") or 0) or (2**intento)
                    log.warning("gemini_rate_limit", intento=intento, espera_s=espera)
                    import asyncio

                    await asyncio.sleep(espera)
                    ultimo_error = LlmError("Gemini rate limit (429)")
                    continue
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
        raise LlmError(f"Gemini rate limit persistente tras {max_intentos} intentos") from ultimo_error

    async def interpretar_mensaje(self, solicitud: str, previos: dict | None = None) -> dict[str, Any]:
        """Clasifica la intencion (saludo/compra/otro) y extrae requisitos, con memoria.

        Devuelve el dict crudo del LLM; el orquestador hace la fusion con `previos`.
        """
        datos = await self._generar_json(
            PROMPT_REQUISITOS.format(solicitud=solicitud, previos=previos or "sin contexto previo")
        )
        return datos

    async def extraer_requisitos(self, solicitud: str, previos: dict | None = None) -> RequisitosCompra:
        """Convierte la solicitud (con memoria de la conversacion) a requisitos."""
        datos = await self.interpretar_mensaje(solicitud, previos)
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
