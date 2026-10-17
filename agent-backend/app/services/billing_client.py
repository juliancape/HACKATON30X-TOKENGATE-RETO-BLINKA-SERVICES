"""Cliente del core de facturacion: envio del registro y estado de la solicitud."""
import httpx

from app.config import get_settings
from app.logging_setup import get_logger

log = get_logger(__name__)


class BillingCoreError(Exception):
    """Error al comunicarse con el core de facturacion."""


class BillingCoreClient:
    """Envia el registro de compra y su decision al core de facturacion."""

    def __init__(self) -> None:
        settings = get_settings()
        self._base_url = settings.billing_core_base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=30.0)
        if settings.billing_core_api_key:
            self._client.headers["Authorization"] = f"Bearer {settings.billing_core_api_key}"

    async def close(self) -> None:
        await self._client.aclose()

    @property
    def configurado(self) -> bool:
        return bool(self._base_url)

    async def enviar_registro(self, registro: dict) -> dict:
        """POST del registro de compra con decision y estado.

        Contrato pendiente de documentacion por el equipo del core. Se usa
        POST {base}/purchase-records como endpoint inicial configurable.
        """
        if not self.configurado:
            raise BillingCoreError("BILLING_CORE_BASE_URL no configurada")
        try:
            respuesta = await self._client.post(f"{self._base_url}/purchase-records", json=registro)
            respuesta.raise_for_status()
            return respuesta.json()
        except httpx.HTTPStatusError as exc:
            log.error("billing_http_error", status=exc.response.status_code)
            raise BillingCoreError(f"Core de facturacion respondio {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            log.error("billing_red_error", error=str(exc))
            raise BillingCoreError("No se pudo contactar el core de facturacion") from exc
