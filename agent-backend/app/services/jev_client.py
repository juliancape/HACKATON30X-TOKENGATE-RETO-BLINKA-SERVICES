"""Cliente del servicio Jev (TypeSafe AI) para la evaluacion de opciones."""
import httpx

from app.config import get_settings
from app.logging_setup import get_logger
from app.models.purchase import OpcionProducto, ResultadoEvaluacion

log = get_logger(__name__)


class JevError(Exception):
    """Error al invocar el servicio de evaluacion Jev."""


class JevClient:
    """Evalua opciones contra el historico de precios y politicas via HTTP."""

    def __init__(self) -> None:
        self._base_url = get_settings().jev_base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=60.0)

    async def close(self) -> None:
        await self._client.aclose()

    @property
    def configurado(self) -> bool:
        return bool(self._base_url)

    async def evaluar(
        self,
        solicitud: str,
        opciones: list[OpcionProducto],
        historico_precios: list[dict],
        politicas: list[dict],
    ) -> list[ResultadoEvaluacion]:
        """Pide la evaluacion estructurada de cada opcion a Jev.

        El contrato esperado (pendiente de confirmar con el servicio final):
        POST {base}/evaluate
        {"solicitud": str, "opciones": [...], "historico_precios": [...], "politicas": [...]}
        -> {"evaluaciones": [{"opcion_id": str, "decision": "aprobar|rechazar|escalar",
                              "motivo": str, "desviacion_pct": float|null, ...}]}
        """
        if not self.configurado:
            raise JevError("JEV_BASE_URL no configurada")
        payload = {
            "solicitud": solicitud,
            "opciones": [o.model_dump(mode="json") for o in opciones],
            "historico_precios": historico_precios,
            "politicas": politicas,
        }
        try:
            respuesta = await self._client.post(f"{self._base_url}/evaluate", json=payload)
            respuesta.raise_for_status()
            datos = respuesta.json()
            return [ResultadoEvaluacion.model_validate(e) for e in datos["evaluaciones"]]
        except httpx.HTTPStatusError as exc:
            log.error("jev_http_error", status=exc.response.status_code)
            raise JevError(f"Jev respondio {exc.response.status_code}") from exc
        except (KeyError, ValueError, httpx.HTTPError) as exc:
            log.error("jev_error", error=str(exc))
            raise JevError("Respuesta invalida de Jev") from exc
