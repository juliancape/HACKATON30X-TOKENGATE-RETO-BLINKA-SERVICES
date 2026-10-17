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
        """Busca productos y tiendas por texto libre.

        La respuesta real de /api/search es {"stores": [...], "popular_dishes": [...]}.
        """
        datos = await self._get("/api/search", params={"q": consulta})
        if isinstance(datos, dict):
            return datos.get("stores", [])
        return datos if isinstance(datos, list) else []

    async def detalle_tienda(self, tienda_id: str) -> dict:
        """Detalle y menu de una tienda."""
        return await self._get(f"/api/store/{tienda_id}")

    async def agregar_al_carrito(
        self,
        tienda_id: str,
        producto_id: str,
        nombre: str,
        cantidad: int = 1,
        precio_cop: int = 0,
    ) -> dict:
        """Agrega un producto al carrito.

        Contrato real de rappi-cli (src/api/app.ts):
        {"storeId": int, "productId": str, "name": str, "quantity"?: int,
         "toppings"?: [int], "price"?: int}
        """
        return await self._post(
            "/api/cart/add",
            {
                "storeId": int(tienda_id),
                "productId": str(producto_id),
                "name": nombre,
                "quantity": cantidad,
                "price": int(precio_cop or 0),
            },
        )

    async def carrito(self) -> dict:
        """Estado actual del carrito."""
        return await self._get("/api/cart")

    async def preview_checkout(self) -> dict:
        """Resumen del pedido hasta checkout, sin pagar."""
        return await self._get("/api/checkout")

    @staticmethod
    def a_opciones(consulta: str, resultados: list[dict]) -> list[OpcionProducto]:
        """Normaliza la respuesta de /api/search de rappi-cli a OpcionProducto.

        El shape real es: {"stores": [{"store_id", "store_name", "eta_value",
        "store_rating_score", "products": [{"product_id", "name", "price", ...}]}]}
        """
        opciones: list[OpcionProducto] = []
        for tienda in resultados:
            productos = tienda.get("products") or []
            for p in productos:
                if not p.get("is_available", True) or not p.get("in_stock", True):
                    continue
                producto_id = str(p.get("product_id") or p.get("id") or "")
                if not producto_id:
                    continue
                opciones.append(
                    OpcionProducto(
                        opcion_id=f"op_{producto_id}",
                        tienda_id=str(tienda.get("store_id") or tienda.get("super_store_id") or ""),
                        tienda_nombre=str(p.get("store_name") or tienda.get("store_name") or tienda.get("brand_name") or "Desconocida"),
                        producto_id=producto_id,
                        producto_nombre=str(p.get("name") or consulta),
                        precio_cop=int(p.get("price") or 0),
                        tiempo_entrega_min=tienda.get("eta_value"),
                        calificacion=tienda.get("store_rating_score"),
                    )
                )
        return opciones
