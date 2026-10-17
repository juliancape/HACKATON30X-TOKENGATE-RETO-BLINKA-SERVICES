"""Cliente de Rappi via el servidor REST del rappi-cli (puerto 3100).

El CLI expone `rappi server` en el puerto 3100. Si el servidor no esta
disponible, este cliente degrada con un error claro en lugar de fingir datos.
"""
import httpx

from app.config import get_settings
from app.logging_setup import get_logger
from app.models.purchase import OpcionProducto

log = get_logger(__name__)


class RappiError(Exception):
    """Error al consultar Rappi (CLI apagado, sesion no autenticada, etc.)."""


class RappiClient:
    """Busqueda de productos y gestion de carrito/checkout contra rappi-cli."""

    def __init__(self) -> None:
        settings = get_settings()
        self._base_url = settings.rappi_api_base_url.rstrip("/")
        self._timeout = settings.rappi_cli_timeout_s
        self._client = httpx.AsyncClient(timeout=self._timeout)

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(self, ruta: str, params: dict | None = None) -> dict:
        try:
            respuesta = await self._client.get(f"{self._base_url}{ruta}", params=params)
            respuesta.raise_for_status()
            return respuesta.json()
        except httpx.HTTPStatusError as exc:
            log.error("rappi_http_error", ruta=ruta, status=exc.response.status_code)
            raise RappiError(f"Rappi CLI respondio {exc.response.status_code} en {ruta}") from exc
        except httpx.HTTPError as exc:
            log.error("rappi_no_disponible", ruta=ruta, error=str(exc))
            raise RappiError(
                "Rappi CLI no disponible. Levantarlo con `rappi server` (puerto 3100)."
            ) from exc

    async def _post(self, ruta: str, json_body: dict | None = None) -> dict:
        try:
            respuesta = await self._client.post(f"{self._base_url}{ruta}", json=json_body)
            respuesta.raise_for_status()
            return respuesta.json()
        except httpx.HTTPStatusError as exc:
            log.error("rappi_http_error", ruta=ruta, status=exc.response.status_code)
            raise RappiError(f"Rappi CLI respondio {exc.response.status_code} en {ruta}") from exc
        except httpx.HTTPError as exc:
            log.error("rappi_no_disponible", ruta=ruta, error=str(exc))
            raise RappiError("Rappi CLI no disponible.") from exc

    async def buscar(self, consulta: str) -> list[dict]:
        """Busca productos y tiendas por texto libre."""
        datos = await self._get("/search", params={"query": consulta})
        return datos.get("results", datos if isinstance(datos, list) else [])

    async def detalle_tienda(self, tienda_id: str) -> dict:
        """Detalle y menu de una tienda."""
        return await self._get(f"/store/{tienda_id}")

    async def agregar_al_carrito(
        self, tienda_id: str, producto_id: str, nombre: str, cantidad: int = 1
    ) -> dict:
        """Agrega un producto al carrito actual."""
        return await self._post(
            "/cart/add",
            {"store": tienda_id, "product": producto_id, "name": nombre, "qty": cantidad},
        )

    async def carrito(self) -> dict:
        """Estado actual del carrito."""
        return await self._get("/cart")

    async def preview_checkout(self) -> dict:
        """Resumen del pedido hasta checkout, sin pagar."""
        return await self._post("/checkout")

    @staticmethod
    def a_opciones(consulta: str, resultados: list[dict]) -> list[OpcionProducto]:
        """Normaliza resultados de busqueda a OpcionProducto tolerando claves variables."""
        opciones: list[OpcionProducto] = []
        for i, item in enumerate(resultados):
            tienda_id = str(item.get("store_id") or item.get("storeId") or item.get("id") or "")
            producto_id = str(item.get("product_id") or item.get("productId") or item.get("id") or f"prod_{i}")
            precio = item.get("price") or item.get("precio") or 0
            opciones.append(
                OpcionProducto(
                    opcion_id=f"op_{i}_{producto_id}",
                    tienda_id=tienda_id,
                    tienda_nombre=str(item.get("store_name") or item.get("storeName") or "Desconocida"),
                    producto_id=producto_id,
                    producto_nombre=str(item.get("name") or item.get("nombre") or consulta),
                    precio_cop=int(precio),
                    tiempo_entrega_min=item.get("delivery_time") or item.get("tiempo_entrega"),
                    calificacion=item.get("rating") or item.get("calificacion"),
                )
            )
        return opciones
