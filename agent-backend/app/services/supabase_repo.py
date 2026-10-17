"""Acceso a Supabase: conversaciones, solicitudes, decisiones y auditoria."""
import uuid
from datetime import datetime, timezone
from typing import Any

from supabase import Client, create_client

from app.config import get_settings
from app.logging_setup import get_logger
from app.models.purchase import EstadoSolicitud, ResultadoEvaluacion

log = get_logger(__name__)


class SupabaseRepo:
    """Repositorio de persistencia en Supabase."""

    def __init__(self) -> None:
        settings = get_settings()
        self._client: Client = create_client(settings.supabase_url, settings.supabase_service_key)

    # ---------------- Conversaciones (estado de la maquina) ----------------

    def obtener_conversacion(self, conversacion_id: str) -> dict[str, Any] | None:
        """Devuelve el estado de la conversacion o None."""
        respuesta = (
            self._client.table("conversations").select("*").eq("id", conversacion_id).maybe_single().execute()
        )
        return respuesta.data

    def guardar_conversacion(self, conversacion_id: str, estado: EstadoSolicitud, contexto: dict[str, Any]) -> None:
        """Crea o actualiza el estado de la conversacion."""
        ahora = datetime.now(timezone.utc).isoformat()
        self._client.table("conversations").upsert(
            {"id": conversacion_id, "estado": estado.value, "contexto": contexto, "actualizado_en": ahora}
        ).execute()

    # ---------------- Solicitudes y decisiones ----------------

    def crear_solicitud(
        self, conversacion_id: str, telefono: str, estado: EstadoSolicitud
    ) -> str:
        """Crea la solicitud de compra y devuelve su id."""
        solicitud_id = str(uuid.uuid4())
        self._client.table("purchase_requests").insert(
            {
                "solicitud_id": solicitud_id,
                "conversacion_id": conversacion_id,
                "telefono_empleado": telefono,
                "estado": estado.value,
            }
        ).execute()
        return solicitud_id

    def actualizar_solicitud(self, solicitud_id: str, estado: EstadoSolicitud, requisitos: dict | None = None) -> None:
        """Actualiza estado y requisitos de la solicitud."""
        campos: dict[str, Any] = {
            "estado": estado.value,
            "actualizado_en": datetime.now(timezone.utc).isoformat(),
        }
        if requisitos is not None:
            campos["requisitos"] = requisitos
        self._client.table("purchase_requests").update(campos).eq("solicitud_id", solicitud_id).execute()

    def guardar_decisiones(self, solicitud_id: str, evaluaciones: list[ResultadoEvaluacion]) -> None:
        """Guarda las decisiones de evaluacion para trazabilidad."""
        if not evaluaciones:
            return
        filas = [e.model_dump(mode="json") | {"solicitud_id": solicitud_id} for e in evaluaciones]
        self._client.table("decisions").insert(filas).execute()

    # ---------------- Datos para Jev ----------------

    def historico_precios(self, texto_producto: str, limite: int = 30) -> list[dict[str, Any]]:
        """Historico de precios por nombre de producto (busqueda por similitud simple)."""
        respuesta = (
            self._client.table("price_history")
            .select("producto_nombre, precio_cop, fecha")
            .ilike("producto_nombre", f"%{texto_producto[:40]}%")
            .order("fecha", desc=True)
            .limit(limite)
            .execute()
        )
        return respuesta.data or []

    def politicas(self) -> list[dict[str, Any]]:
        """Politicas corporativas activas."""
        respuesta = self._client.table("policies").select("*").eq("activa", True).execute()
        return respuesta.data or []

    def gasto_diario(self, telefono: str) -> int:
        """Suma de pedidos completados hoy para el empleado."""
        hoy = datetime.now(timezone.utc).date().isoformat()
        respuesta = (
            self._client.table("purchase_requests")
            .select("total_cop")
            .eq("telefono_empleado", telefono)
            .eq("estado", "completada")
            .gte("creado_en", f"{hoy}T00:00:00Z")
            .execute()
        )
        return sum((fila.get("total_cop") or 0) for fila in respuesta.data or [])

    # ---------------- Auditoria ----------------

    def registrar_auditoria(self, conversacion_id: str, evento: str, detalle: dict[str, Any]) -> None:
        """Registra un evento de auditoria; nunca debe romper el flujo principal."""
        try:
            self._client.table("audit_events").insert(
                {"conversacion_id": conversacion_id, "evento": evento, "detalle": detalle}
            ).execute()
        except Exception as exc:  # noqa: BLE001 - auditoria es best-effort
            log.warning("auditoria_fallo", evento=evento, error=str(exc))
