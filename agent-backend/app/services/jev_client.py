"""Cliente del servicio Jev (TypeSafe AI).

API real documentada en https://docs.typesafe.ai/api.md:
POST https://api.typesafe.ai/v1/systemone
{"state": ..., "model": "jev-latest", "questions": {...}}
-> {"answers": {<question_id>: {"choice"/"noul"/"score", "probabilities", "confidence", ...}}}

Uso: una pregunta Choice por opcion (aprobar/rechazar/escalar) + un Noul de
precio consistente, todas atomicas y evaluadas en paralelo contra el mismo estado.
"""
import httpx

from app.config import get_settings
from app.logging_setup import get_logger
from app.models.purchase import Decision, OpcionProducto, ResultadoEvaluacion

log = get_logger(__name__)

JEV_BASE_URL = "https://api.typesafe.ai/v1/systemone"


class JevError(Exception):
    """Error al invocar el servicio de evaluacion Jev."""


class JevClient:
    """Evalua opciones contra el historico de precios y politicas via TypeSafe AI."""

    def __init__(self) -> None:
        settings = get_settings()
        self._api_key = settings.jev_api_key
        self._client = httpx.AsyncClient(timeout=60.0)

    async def close(self) -> None:
        await self._client.aclose()

    @property
    def configurado(self) -> bool:
        return bool(self._api_key)

    def _construir_preguntas(self, opciones: list[OpcionProducto]) -> dict:
        """Una Choice atomica por opcion + Noul de precio razonable por opcion."""
        preguntas: dict = {}
        for opcion in opciones:
            preguntas[f"decision_{opcion.opcion_id}"] = {
                "type": "choice",
                "instructions": {
                    "pregunta": (
                        "Un empleado de una empresa quiere comprar esta opcion. "
                        "Decide si la compra corporativa debe aprobarse, rechazarse o escalarse a revision humana."
                    ),
                    "opcion": opcion.model_dump(mode="json"),
                    "solicitud": "ver estado.solicitud",
                    "historico": "ver estado.historico_precios",
                    "politicas": "ver estado.politicas",
                },
                "criteria": {
                    "aprobar": "Precio razonable frente al historico, cumple politicas y encaja con la solicitud",
                    "rechazar": "Precio desviado del historico o viola politicas o no encaja con la solicitud",
                    "escalar": "Informacion insuficiente o caso ambiguo que requiere revision humana",
                },
            }
            preguntas[f"precio_ok_{opcion.opcion_id}"] = {
                "type": "noul",
                "instructions": {
                    "pregunta": (
                        f"El precio de {opcion.producto_nombre} ({opcion.precio_cop} COP) "
                        "es consistente con el historico de precios para este tipo de producto?"
                    ),
                    "historico": "ver estado.historico_precios",
                },
                "criteria": {
                    "true": "Precio dentro del rango historico razonable",
                    "false": "Precio atipicamente alto o bajo frente al historico",
                },
            }
        return preguntas

    async def evaluar(
        self,
        solicitud: str,
        opciones: list[OpcionProducto],
        historico_precios: list[dict],
        politicas: list[dict],
    ) -> list[ResultadoEvaluacion]:
        """Evalua todas las opciones en una sola llamada (preguntas atomicas en paralelo)."""
        if not self.configurado:
            raise JevError("JEV_API_KEY no configurada")
        if not opciones:
            return []

        estado = {
            "solicitud": solicitud,
            "opciones": [o.model_dump(mode="json") for o in opciones],
            "historico_precios": historico_precios,
            "politicas": politicas,
        }
        payload = {
            "state": estado,
            "model": "jev-latest",
            "questions": self._construir_preguntas(opciones),
        }
        try:
            respuesta = await self._client.post(
                JEV_BASE_URL,
                headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                json=payload,
            )
            respuesta.raise_for_status()
            datos = respuesta.json()
        except httpx.HTTPStatusError as exc:
            log.error("jev_http_error", status=exc.response.status_code, cuerpo=exc.response.text[:300])
            raise JevError(f"Jev respondio {exc.response.status_code}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            log.error("jev_error", error=str(exc))
            raise JevError("Respuesta invalida de Jev") from exc

        respuestas = datos.get("answers", {})
        resultados: list[ResultadoEvaluacion] = []
        for opcion in opciones:
            decision_resp = respuestas.get(f"decision_{opcion.opcion_id}", {})
            precio_resp = respuestas.get(f"precio_ok_{opcion.opcion_id}", {})
            eleccion = str(decision_resp.get("choice", "")).lower()
            decision = Decision(eleccion) if eleccion in Decision._value2member_map_ else Decision.ESCALAR
            prob_decision = (decision_resp.get("probabilities") or {}).get(eleccion)
            precio_ok = precio_resp.get("noul")
            resultados.append(
                ResultadoEvaluacion(
                    opcion_id=opcion.opcion_id,
                    decision=decision,
                    motivo=(
                        f"Jev: {eleccion or 'sin respuesta'}"
                        f" (confianza {decision_resp.get('confidence')}, prob {prob_decision})"
                        f"; precio consistente con historico: {precio_ok}"
                    ),
                    desviacion_pct=None,
                )
            )
        return resultados
