"""Orquestador del flujo de compra: maquina de estados por conversacion.
Estados:
  NUEVA -> RECOPILANDO_REQUISITOS (LLM extrae requisitos, se confirma)
  RECOPILANDO_REQUISITOS -> BUSCANDO_OPCIONES (Rappi + historico + Jev + politicas)
  BUSCANDO_OPCIONES -> ESPERANDO_SELECCION (botones con opciones aprobadas)
  ESPERANDO_SELECCION -> CHECKOUT_PREPARADO (revalida precio, prepara checkout)
  CHECKOUT_PREPARADO -> COMPLETADA (registro enviado al core de facturacion)
  Rechazo/escalas -> ESCALADA o RECHAZADA, con nueva vuelta de requisitos si el
  empleado rechaza las opciones.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.config import Settings, get_settings
from app.domain.policies import ContextoGasto, filtrar_aprobables, mejores_opciones
from app.logging_setup import get_logger
from app.models.kapso import TextoEntrante
from app.models.purchase import Decision, EstadoSolicitud, RequisitosCompra
from app.services.billing_client import BillingCoreClient, BillingCoreError
from app.services.jev_client import JevClient, JevError
from app.services.kapso_client import KapsoClient
from app.services.llm_service import GeminiService, LlmError
from app.services.rappi_client import RappiClient, RappiError
from app.services.supabase_repo import SupabaseRepo

log = get_logger(__name__)

ID_OPCION_PREFIX = "sel:"
ID_RECHAZO = "rechazo"

_orquestador: Orquestador | None = None


def get_orquestador() -> "Orquestador":
    """Instancia unica del orquestador (se construye perezosamente)."""
    global _orquestador
    if _orquestador is None:
        _orquestador = Orquestador()
    return _orquestador


class OrquestadorError(Exception):
    """Error del flujo de orquestacion."""


class Orquestador:
    """Coordina todos los servicios y mantiene el estado por conversacion."""

    def __init__(self) -> None:
        self.settings: Settings = get_settings()
        self.kapso = KapsoClient()
        self.llm = GeminiService()
        self.rappi = RappiClient()
        self.repo = SupabaseRepo()
        self.jev = JevClient()
        self.billing = BillingCoreClient()

    async def cerrar(self) -> None:
        """Cierra los clientes HTTP."""
        await self.kapso.close()
        await self.llm.close()
        await self.rappi.close()
        await self.jev.close()
        await self.billing.close()

    # ------------------------------------------------------------------ utils

    async def manejar_mensaje(self, conversacion_id: str, telefono: str, contenido: TextoEntrante) -> None:
        """Punto de entrada: enruta segun el estado de la conversacion."""
        convo = self.repo.obtener_conversacion(conversacion_id)
        estado = EstadoSolicitud((convo or {}).get("estado", EstadoSolicitud.NUEVA.value))
        contexto = (convo or {}).get("contexto", {})
        log.info("mensaje_recibido", conversacion_id=conversacion_id, estado=estado, tipo=contenido.tipo)

        try:
            if contenido.tipo == "flow":
                await self._procesar_flow(conversacion_id, telefono, contenido, contexto)
            elif estado in (EstadoSolicitud.NUEVA, EstadoSolicitud.RECOPILANDO_REQUISITOS):
                await self._fase_requisitos(conversacion_id, telefono, contenido, contexto)
            elif estado == EstadoSolicitud.ESPERANDO_SELECCION:
                await self._fase_seleccion(conversacion_id, telefono, contenido, contexto)
            elif estado == EstadoSolicitud.CHECKOUT_PREPARADO:
                await self.kapso.enviar_texto(telefono, "El pedido ya esta preparado en checkout. Sin pago ejecutado.")
            elif estado == EstadoSolicitud.COMPLETADA:
                await self._reiniciar(conversacion_id, telefono)
            else:
                await self.kapso.enviar_texto(
                    telefono, "Tu solicitud esta en revision o escalada. Te avisaremos por este canal."
                )
        except (RappiError, LlmError, JevError, BillingCoreError, OrquestadorError) as exc:
            log.error("fallo_flujo", conversacion_id=conversacion_id, error=str(exc))
            self.repo.registrar_auditoria(conversacion_id, "error_flujo", {"error": str(exc)})
            await self.kapso.enviar_texto(
                telefono,
                "Tuvimos un problema procesando tu solicitud. Intenta de nuevo en unos minutos.",
            )

    async def _procesar_flow(
        self, conversacion_id: str, telefono: str, contenido: TextoEntrante, contexto: dict
    ) -> None:
        """Recibe la respuesta del WhatsApp Flow, valida en backend y fusiona requisitos."""
        datos = contenido.flow_data or {}
        descripcion = str(datos.get("descripcion") or "").strip()
        if not descripcion:
            await self.kapso.enviar_texto(telefono, "El formulario no trajo descripcion. Escribe que necesitas.")
            return
        # Validacion determinista en backend (no confiar en el formulario)
        presupuesto_crudo = str(datos.get("presupuesto") or "").strip()
        personas_crudo = str(datos.get("personas") or "").strip()
        restricciones = [r for r in str(datos.get("restricciones") or "").split(",") if r.strip()]
        presupuesto = int(presupuesto_crudo) if presupuesto_crudo.isdigit() else None
        personas = int(personas_crudo) if personas_crudo.isdigit() else 1

        previos = contexto.get("requisitos") or {}
        contexto["requisitos"] = {
            "descripcion": descripcion,
            "presupuesto_maximo_cop": presupuesto or previos.get("presupuesto_maximo_cop"),
            "cantidad_personas": max(1, personas),
            "restricciones": restricciones or previos.get("restricciones", []),
        }
        contexto.pop("esperando_flow", None)
        self.repo.guardar_conversacion(conversacion_id, EstadoSolicitud.RECOPILANDO_REQUISITOS, contexto)
        req = contexto["requisitos"]
        await self.kapso.enviar_botones(
            telefono,
            f"Con estos datos busco:\n- {req['descripcion']}\n- Personas: {req['cantidad_personas']}\n"
            f"- Presupuesto: {req['presupuesto_maximo_cop'] or 'sin limite'} COP",
            [{"id": "req:buscar", "titulo": "Buscar opciones"}, {"id": "req:corregir", "titulo": "Corregir"}],
        )
        contexto["esperando_confirmacion_requisitos"] = True
        self.repo.guardar_conversacion(conversacion_id, EstadoSolicitud.RECOPILANDO_REQUISITOS, contexto)

    async def _reiniciar(self, conversacion_id: str, telefono: str) -> None:
        self.repo.guardar_conversacion(conversacion_id, EstadoSolicitud.NUEVA, {})
        await self.kapso.enviar_texto(telefono, "Listo! Cuentame que quieres pedir y empezamos de nuevo.")

    # ------------------------------------------------------- fase requisitos

    async def _fase_requisitos(
        self, conversacion_id: str, telefono: str, contenido: TextoEntrante, contexto: dict
    ) -> None:
        texto = contenido.texto_libre
        if not texto:
            await self.kapso.enviar_texto(
                telefono, "Escribe que te gustaria comer o comprar (ej: 'sushi para 2, max 50 mil')."
            )
            return

        requisitos = await self.llm.extraer_requisitos(texto)
        contexto["requisitos"] = requisitos.model_dump(mode="json")
        contexto["solicitud_texto"] = texto

        # Si falta presupuesto, pedirlo por WhatsApp Flow (si hay Flow configurado)
        flow_id = self.settings.kapso_flow_id_requisitos
        if requisitos.presupuesto_maximo_cop is None and flow_id:
            prefill = {"descripcion": requisitos.descripcion, "personas": str(requisitos.cantidad_personas)}
            if requisitos.restricciones:
                prefill["restricciones"] = ", ".join(requisitos.restricciones)
            await self.kapso.enviar_flow(
                telefono, flow_id, "Falta tu presupuesto maximo. Completalo aqui:", "Completar", prefill
            )
            contexto["esperando_flow"] = True
            self.repo.guardar_conversacion(conversacion_id, EstadoSolicitud.RECOPILANDO_REQUISITOS, contexto)
            return

        self.repo.guardar_conversacion(conversacion_id, EstadoSolicitud.RECOPILANDO_REQUISITOS, contexto)

        resumen = (
            f"Entendi esto:\n- Que: {requisitos.descripcion}\n"
            f"- Personas: {requisitos.cantidad_personas}\n"
            f"- Presupuesto: {requisitos.presupuesto_maximo_cop or 'sin limite indicado'} COP\n"
            f"- Restricciones: {', '.join(requisitos.restricciones) or 'ninguna'}"
        )
        await self.kapso.enviar_botones(
            telefono,
            resumen,
            [
                {"id": "req:buscar", "titulo": "Buscar opciones"},
                {"id": "req:corregir", "titulo": "Corregir datos"},
            ],
        )
        # Guardamos las IDs de respuesta para la siguiente interaccion
        contexto["esperando_confirmacion_requisitos"] = True
        self.repo.guardar_conversacion(conversacion_id, EstadoSolicitud.RECOPILANDO_REQUISITOS, contexto)

    # --------------------------------------------------------- busqueda + jev

    async def _buscar_y_presentar(self, conversacion_id: str, telefono: str, contexto: dict) -> None:
        """Flujo central: Rappi -> Supabase -> Jev -> politicas -> botones."""
        requisitos = RequisitosCompra.model_validate(contexto["requisitos"])
        self.repo.guardar_conversacion(conversacion_id, EstadoSolicitud.BUSCANDO_OPCIONES, contexto)

        resultados = await self.rappi.buscar(requisitos.descripcion)
        opciones = self.rappi.a_opciones(requisitos.descripcion, resultados)
        if not opciones:
            await self.kapso.enviar_texto(
                telefono, "No encontre resultados en Rappi para eso. Prueba con otra descripcion."
            )
            return

        gasto_diario = self.repo.gasto_diario(telefono)
        contexto_gasto = ContextoGasto(gasto_diario_cop=gasto_diario)
        evaluaciones = filtrar_aprobables(opciones, contexto_gasto, self.settings)

        # Jev evalua el contexto completo (historico de precios + politicas)
        historico = self.repo.historico_precios(requisitos.descripcion)
        politicas = self.repo.politicas()
        try:
            evaluaciones_jev = await self.jev.evaluar(requisitos.descripcion, opciones, historico, politicas)
            # Fusion: si Jev no aprueba una opcion, tampoco se presenta
            no_aprobadas_jev = {e.opcion_id for e in evaluaciones_jev if e.decision != Decision.APROBAR}
            for e in evaluaciones:
                if e.opcion_id in no_aprobadas_jev and e.decision == Decision.APROBAR:
                    e.decision = Decision.ESCALAR
                    e.motivo = "Escala sugerida por Jev: " + next(
                        (j.motivo for j in evaluaciones_jev if j.opcion_id == e.opcion_id), "sin motivo"
                    )
        except JevError as exc:
            log.warning("jev_no_disponible_continua_con_politicas", error=str(exc))
            self.repo.registrar_auditoria(conversacion_id, "jev_no_disponible", {"error": str(exc)})

        opciones_por_id = {o.opcion_id: o for o in opciones}
        seleccionables = mejores_opciones(evaluaciones, opciones_por_id, cantidad=3)
        self.repo.guardar_decisiones(contexto.get("solicitud_id", conversacion_id), evaluaciones)
        self.repo.registrar_auditoria(
            conversacion_id,
            "evaluacion",
            {
                "total_opciones": len(opciones),
                "aprobadas": sum(1 for e in evaluaciones if e.decision == Decision.APROBAR),
                "escaladas": sum(1 for e in evaluaciones if e.decision == Decision.ESCALAR),
            },
        )

        if not seleccionables:
            await self.kapso.enviar_texto(
                telefono,
                "Ninguna opcion cumple las politicas corporativas. Tu solicitud quedo registrada como escalada.",
            )
            self.repo.guardar_conversacion(conversacion_id, EstadoSolicitud.ESCALADA, contexto)
            return

        mensaje = await self.llm.redactar_presentacion(
            contexto.get("solicitud_texto", requisitos.descripcion),
            [o.model_dump() for o in seleccionables],
        )
        filas = [
            {
                "id": f"{ID_OPCION_PREFIX}{o.opcion_id}",
                "titulo": f"{o.producto_nombre[:20]} - {o.precio_cop} COP",
                "descripcion": f"{o.tienda_nombre}",
            }
            for o in seleccionables
        ]
        filas.append({"id": ID_RECHAZO, "titulo": "Ninguna me convence", "descripcion": "Buscar otras opciones"})
        await self.kapso.enviar_lista(telefono, mensaje, filas)

        contexto["opciones_presentadas"] = [o.model_dump(mode="json") for o in seleccionables]
        self.repo.guardar_conversacion(conversacion_id, EstadoSolicitud.ESPERANDO_SELECCION, contexto)

    # ------------------------------------------------------- fase seleccion

    async def _fase_seleccion(
        self, conversacion_id: str, telefono: str, contenido: TextoEntrante, contexto: dict
    ) -> None:
        # Confirmacion de requisitos pendiente?
        if contexto.get("esperando_confirmacion_requisitos") and contenido.boton_id:
            if contenido.boton_id == "req:corregir":
                contexto["esperando_confirmacion_requisitos"] = False
                self.repo.guardar_conversacion(conversacion_id, EstadoSolicitud.NUEVA, contexto)
                await self.kapso.enviar_texto(telefono, "OK, escribe de nuevo que necesitas.")
                return
            if contenido.boton_id == "req:buscar":
                contexto["esperando_confirmacion_requisitos"] = False
                await self._buscar_y_presentar(conversacion_id, telefono, contexto)
                return

        if contenido.boton_id and contenido.boton_id.startswith(ID_OPCION_PREFIX):
            await self._preparar_checkout(conversacion_id, telefono, contenido.boton_id[len(ID_OPCION_PREFIX):], contexto)
        elif contenido.boton_id == ID_RECHAZO or (contenido.texto_libre and not contenido.boton_id):
            contexto.pop("opciones_presentadas", None)
            self.repo.guardar_conversacion(conversacion_id, EstadoSolicitud.NUEVA, contexto)
            flow_id = self.settings.kapso_flow_id_requisitos
            if contenido.boton_id == ID_RECHAZO and flow_id:
                # Reevaluacion: preguntar que desea modificar via Flow prellenado
                requisitos = contexto.get("requisitos") or {}
                prefill = {
                    "descripcion": requisitos.get("descripcion", ""),
                    "personas": str(requisitos.get("cantidad_personas", 1)),
                }
                if requisitos.get("presupuesto_maximo_cop"):
                    prefill["presupuesto"] = str(requisitos["presupuesto_maximo_cop"])
                if requisitos.get("restricciones"):
                    prefill["restricciones"] = ", ".join(requisitos["restricciones"])
                await self.kapso.enviar_flow(
                    telefono, flow_id, "Ajusta lo que quieras cambiar y volvemos a buscar:", "Rebuscar", prefill
                )
                self.repo.guardar_conversacion(conversacion_id, EstadoSolicitud.RECOPILANDO_REQUISITOS, contexto)
            else:
                await self.kapso.enviar_texto(
                    telefono, "Sin problema. Describe mejor que buscas y volvemos a buscar."
                )
        else:
            await self.kapso.enviar_texto(telefono, "Elige una de las opciones con los botones, por favor.")

    async def _preparar_checkout(
        self, conversacion_id: str, telefono: str, opcion_id: str, contexto: dict
    ) -> None:
        """Revalida precio y condiciones, agrega al carrito y prepara checkout."""
        opciones = contexto.get("opciones_presentadas", [])
        opcion = next((o for o in opciones if o["opcion_id"] == opcion_id), None)
        if not opcion:
            await self.kapso.enviar_texto(telefono, "Esa opcion ya no esta disponible. Buscamos de nuevo?")
            return

        # Revalidacion obligatoria contra politicas duras antes del checkout
        from app.models.purchase import OpcionProducto

        gasto_diario = self.repo.gasto_diario(telefono)
        validacion = filtrar_aprobables([OpcionProducto.model_validate(opcion)], ContextoGasto(gasto_diario), self.settings)[0]
        if validacion.decision != Decision.APROBAR:
            await self.kapso.enviar_texto(
                telefono, f"El precio cambio o ya no cumple politicas: {validacion.motivo}. Buscamos de nuevo."
            )
            self.repo.guardar_conversacion(conversacion_id, EstadoSolicitud.NUEVA, contexto)
            return

        carrito = await self.rappi.agregar_al_carrito(
            opcion["tienda_id"], opcion["producto_id"], opcion["producto_nombre"], cantidad=1
        )
        checkout = await self.rappi.preview_checkout()

        solicitud_id = contexto.get("solicitud_id")
        registro = {
            "solicitud_id": solicitud_id or conversacion_id,
            "conversacion_id": conversacion_id,
            "telefono_empleado": telefono,
            "opcion_elegida": opcion,
            "carrito": carrito,
            "checkout_preview": checkout,
            "decision": "aprobada",
            "estado": "checkout_preparado",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if self.billing.configurado:
            await self.billing.enviar_registro(registro)

        self.repo.guardar_conversacion(conversacion_id, EstadoSolicitud.CHECKOUT_PREPARADO, contexto)
        if solicitud_id:
            self.repo.actualizar_solicitud(solicitud_id, EstadoSolicitud.CHECKOUT_PREPARADO)
        self.repo.registrar_auditoria(conversacion_id, "checkout_preparado", {"opcion_id": opcion_id})
        await self.kapso.enviar_texto(
            telefono,
            "Pedido preparado hasta checkout (sin pago). El core de facturacion recibio el registro de tu solicitud.",
        )
