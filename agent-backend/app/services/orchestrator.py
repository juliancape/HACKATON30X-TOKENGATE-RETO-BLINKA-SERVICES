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
from app.domain.policies import filtrar_por_presupuesto, mejores_opciones, validar_presupuesto
from app.logging_setup import get_logger
from app.models.kapso import TextoEntrante
from app.models.purchase import Decision, EstadoSolicitud, RequisitosCompra
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

    async def cerrar(self) -> None:
        """Cierra los clientes HTTP."""
        await self.kapso.close()
        await self.llm.close()
        await self.rappi.close()
        await self.jev.close()

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
            elif contenido.boton_id and contenido.boton_id.startswith("req:"):
                await self._manejar_confirmacion_requisitos(conversacion_id, telefono, contenido, contexto)
            elif estado in (
                EstadoSolicitud.NUEVA,
                EstadoSolicitud.RECOPILANDO_REQUISITOS,
                EstadoSolicitud.BUSCANDO_OPCIONES,
            ):
                await self._fase_requisitos(conversacion_id, telefono, contenido, contexto)
            elif estado == EstadoSolicitud.ESPERANDO_SELECCION:
                await self._fase_seleccion(conversacion_id, telefono, contenido, contexto)
            elif estado in (EstadoSolicitud.CHECKOUT_PREPARADO, EstadoSolicitud.COMPLETADA):
                # Nuevo pedido: conservamos memoria pero limpiamos el pedido anterior
                contexto.pop("opciones_presentadas", None)
                self.repo.guardar_conversacion(conversacion_id, EstadoSolicitud.NUEVA, contexto)
                await self._fase_requisitos(conversacion_id, telefono, contenido, contexto)
            else:
                await self.kapso.enviar_texto(
                    telefono, "Tu solicitud esta en revision o escalada. Te avisaremos por este canal."
                )
        except (RappiError, LlmError, JevError, OrquestadorError) as exc:
            log.error("fallo_flujo", conversacion_id=conversacion_id, error=str(exc))
            self.repo.registrar_auditoria(conversacion_id, "error_flujo", {"error": str(exc)})
            # Recuperar la conversacion a un estado accionable; el contexto se conserva
            self.repo.guardar_conversacion(conversacion_id, EstadoSolicitud.NUEVA, contexto)
            await self.kapso.enviar_texto(
                telefono,
                "Tuvimos un problema procesando tu solicitud. Intenta de nuevo en unos minutos.",
            )
        except Exception as exc:  # noqa: BLE001 - nunca dejar al empleado sin respuesta
            log.error("fallo_inesperado", conversacion_id=conversacion_id, error=str(exc), exc_info=True)
            self.repo.guardar_conversacion(conversacion_id, EstadoSolicitud.NUEVA, contexto)
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

    async def _manejar_confirmacion_requisitos(
        self, conversacion_id: str, telefono: str, contenido: TextoEntrante, contexto: dict
    ) -> None:
        """Botones de confirmacion de requisitos (funciona en cualquier estado de recoleccion)."""
        if contenido.boton_id == "req:corregir":
            self.repo.guardar_conversacion(conversacion_id, EstadoSolicitud.NUEVA, contexto)
            await self.kapso.enviar_texto(telefono, "OK, escribe de nuevo que necesitas.")
            return
        if contenido.boton_id == "req:buscar":
            await self._buscar_y_presentar(conversacion_id, telefono, contexto)
            return
        await self.kapso.enviar_texto(telefono, "Elige una de las opciones con los botones, por favor.")

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

        previos = contexto.get("requisitos") or {}
        analisis = await self.llm.interpretar_mensaje(texto, previos)

        # Saludo u off-topic: presentarse y pedir lo necesario
        if analisis.get("intencion") != "compra":
            await self.kapso.enviar_texto(
                telefono,
                "Hola! Soy el agente de compras corporativas: busco opciones reales en Rappi y preparo "
                "tu pedido segun las politicas de la empresa.\n\n"
                "Para buscarte bien dime:\n"
                "1. Que quieres comer o comprar\n"
                "2. Para cuantas personas\n"
                "3. Presupuesto maximo (opcional, si no lo das busco igual)\n"
                "4. Restricciones (alergias, tipo de comida, etc)\n\n"
                "Ej: 'sushi para 2, max 40 mil'",
            )
            return

        # Fusion con memoria: lo ya dicho se conserva si el nuevo mensaje no lo trae
        personas = (
            analisis.get("cantidad_personas")
            if analisis.get("cantidad_personas") is not None
            else (previos.get("cantidad_personas") or 1)
        )
        requisitos = RequisitosCompra(
            descripcion=str(analisis.get("descripcion") or previos.get("descripcion") or texto),
            presupuesto_maximo_cop=(
                analisis.get("presupuesto_maximo_cop")
                if analisis.get("presupuesto_maximo_cop") is not None
                else previos.get("presupuesto_maximo_cop")
            ),
            cantidad_personas=max(1, int(personas or 1)),
            restricciones=analisis.get("restricciones") or previos.get("restricciones", []),
        )
        contexto["requisitos"] = requisitos.model_dump(mode="json")
        contexto["solicitud_texto"] = f"{previos.get('solicitud_texto', '')} {texto}".strip()

        # Insistir por lo que falta antes de buscar
        faltantes: list[str] = []
        if not requisitos.descripcion:
            faltantes.append("que quieres comer o comprar")

        botones_extra: list[dict[str, str]] = []
        if requisitos.presupuesto_maximo_cop is None:
            faltantes.append("presupuesto maximo (o busca sin limite)")
            botones_extra = [{"id": "req:buscar", "titulo": "Buscar sin limite"}]

        if faltantes:
            detalle = "\n".join(f"- {f}" for f in faltantes)
            botones = botones_extra + ([{"id": "req:corregir", "titulo": "Volver a escribir"}] if botones_extra else [])
            await self.kapso.enviar_botones(
                telefono, f"Me falta informacion para buscar bien:\n{detalle}", botones
            )
            self.repo.guardar_conversacion(conversacion_id, EstadoSolicitud.RECOPILANDO_REQUISITOS, contexto)
            return

        await self.kapso.enviar_botones(
            telefono,
            f"📋 *Entendi esto:*\n🍔 {requisitos.descripcion}\n"
            f"👥 {requisitos.cantidad_personas} persona(s) → {requisitos.cantidad_personas} unidad(es)\n"
            f"💰 Presupuesto TOTAL: *${requisitos.presupuesto_maximo_cop:,} COP*"
            f"⚠️ Restricciones: {', '.join(requisitos.restricciones) or 'ninguna'}",
            [
                {"id": "req:buscar", "titulo": "🔎 Buscar opciones"},
                {"id": "req:corregir", "titulo": "✏️ Corregir datos"},
            ],
        )
        self.repo.guardar_conversacion(conversacion_id, EstadoSolicitud.RECOPILANDO_REQUISITOS, contexto)
        # Crear la solicitud trazable (una por conversacion) con FK a conversations
        if not contexto.get("solicitud_id"):
            contexto["solicitud_id"] = self.repo.crear_solicitud(
                conversacion_id, telefono, EstadoSolicitud.RECOPILANDO_REQUISITOS
            )
            self.repo.actualizar_solicitud(
                contexto["solicitud_id"], EstadoSolicitud.RECOPILANDO_REQUISITOS, requisitos.model_dump(mode="json")
            )
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

        cantidad_personas = max(1, int(requisitos.cantidad_personas or 1))
        evaluaciones = filtrar_por_presupuesto(opciones, requisitos.presupuesto_maximo_cop, cantidad_personas)

        # Jev solo sobre las candidatas que ya pasaron las politicas duras,
        # con tope para no disparar cientos de preguntas atomicas.
        LIMITE_CANDIDATAS_JEV = 12
        opciones_por_id = {o.opcion_id: o for o in opciones}
        candidatas = [e for e in evaluaciones if e.decision == Decision.APROBAR][:LIMITE_CANDIDATAS_JEV]
        historico = self.repo.historico_precios(requisitos.descripcion)
        politicas = self.repo.politicas()
        try:
            evaluaciones_jev = await self.jev.evaluar(
                requisitos.descripcion,
                [opciones_por_id[e.opcion_id] for e in candidatas],
                historico,
                politicas,
            )
            # Jev es solo un filtro de calidad y ranking: ya no decide aprobaciones.
            # La aprobacion/rechazo/escala la hace el sistema pagador (pagador_reviews).
            por_id_jev = {e.opcion_id: e for e in evaluaciones_jev}
            for e in evaluaciones:
                jev = por_id_jev.get(e.opcion_id)
                if jev is None:
                    continue
                if e.decision == Decision.APROBAR and jev.decision == Decision.RECHAZAR:
                    e.decision = Decision.RECHAZAR
                e.motivo = jev.motivo
        except JevError as exc:
            log.warning("jev_no_disponible_continua_con_politicas", error=str(exc))
            self.repo.registrar_auditoria(conversacion_id, "jev_no_disponible", {"error": str(exc)})

        seleccionables = mejores_opciones(evaluaciones, opciones_por_id, cantidad=3)
        self.repo.guardar_decisiones(contexto.get("solicitud_id", conversacion_id), evaluaciones)
        # Bootstrap del historico de precios con lo observado en esta busqueda
        self.repo.registrar_precios(
            [opciones_por_id[e.opcion_id].model_dump(mode="json") for e in candidatas],
            requisitos.descripcion,
        )
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
                "😕 Ninguna opcion entra en tu presupuesto o paso el filtro de calidad. "
                "Prueba con otro producto o un presupuesto mayor.",
            )
            self.repo.guardar_conversacion(conversacion_id, EstadoSolicitud.NUEVA, contexto)
            return

        mensaje = await self.llm.redactar_presentacion(
            contexto.get("solicitud_texto", requisitos.descripcion),
            [o.model_dump() for o in seleccionables],
        )
        # Imagenes de producto con caption formateado (una por opcion)
        for i, o in enumerate(seleccionables, start=1):
            if o.imagen_url:
                caption = (
                    f"*{i}. {o.producto_nombre}*\n"
                    f"🏪 {o.tienda_nombre}\n"
                    f"💰 *${o.precio_cop:,} COP*"
                    + (f"\n⏱ {o.tiempo_entrega_min} min" if o.tiempo_entrega_min else "")
                )
                try:
                    await self.kapso.enviar_imagen(telefono, o.imagen_url, caption)
                    log.info("imagen_enviada", opcion_id=o.opcion_id, url=o.imagen_url)
                except Exception as exc:  # noqa: BLE001 - la imagen no debe romper la lista
                    log.warning("imagen_no_enviada", opcion_id=o.opcion_id, error=str(exc))

        filas = [
            {
                "id": f"{ID_OPCION_PREFIX}{o.opcion_id}",
                "titulo": f"{i}. {o.producto_nombre[:20]}",
                "descripcion": f"${o.precio_cop:,} COP - {o.tienda_nombre[:40]}",
            }
            for i, o in enumerate(seleccionables, start=1)
        ]
        filas.append({"id": ID_RECHAZO, "titulo": "Ninguna me convence", "descripcion": "Buscar otras opciones"})
        await self.kapso.enviar_lista(telefono, mensaje + "\n\n¿Cual te llamo la atencion? 👇", filas)

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

        # Revalidacion obligatoria contra politicas duras antes del checkout,
        # con el TOTAL real (precio unitario * cantidad de personas)
        from app.models.purchase import OpcionProducto

        requisitos = RequisitosCompra.model_validate(contexto.get("requisitos") or {})
        cantidad = max(1, int(requisitos.cantidad_personas or 1))
        total = int(opcion.get("precio_cop") or 0) * cantidad
        # validar_presupuesto multiplica precio x cantidad por si sola:
        # pasar la opcion ORIGINAL, no el total ya calculado (evita doble multiplicacion)
        opcion_original = OpcionProducto.model_validate(opcion)
        validacion = validar_presupuesto(opcion_original, requisitos.presupuesto_maximo_cop, cantidad)
        if validacion.decision != Decision.APROBAR:
            await self.kapso.enviar_texto(
                telefono,
                f"⚠️ El precio cambió o ya no entra en tu presupuesto: {validacion.motivo}\nBuscamos de nuevo.",
            )
            self.repo.guardar_conversacion(conversacion_id, EstadoSolicitud.NUEVA, contexto)
            return

        carrito = await self.rappi.agregar_al_carrito(
            opcion["tienda_id"],
            opcion["producto_id"],
            opcion["producto_nombre"],
            cantidad=cantidad,
            precio_cop=int(opcion.get("precio_cop") or 0),
        )
        checkout = await self.rappi.preview_checkout()

        solicitud_id = contexto.get("solicitud_id") or conversacion_id
        registro = {
            "conversacion_id": conversacion_id,
            "telefono_empleado": telefono,
            "opcion_elegida": opcion,
            "cantidad": cantidad,
            "carrito": carrito,
            "checkout_preview": checkout,
            "estado": "checkout_preparado",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        # Insertar la compra como subject del sistema pagador (blinka):
        # el core de facturacion es quien aprueba/rechaza via pagador_reviews.
        org_id = self.settings.pagador_org_id
        try:
            self.repo.insertar_subject_compra(
                subject_id=solicitud_id,
                org_id=org_id,
                referencia=f"compra-{conversacion_id[:8]}",
                total_cop=total,
                payload=registro,
            )
        except Exception as exc:  # noqa: BLE001 - el insert al pagador no debe tumbar el flujo
            log.error("pagador_insert_fallo", error=str(exc))
            self.repo.registrar_auditoria(conversacion_id, "pagador_insert_fallo", {"error": str(exc)})

        self.repo.guardar_conversacion(conversacion_id, EstadoSolicitud.CHECKOUT_PREPARADO, contexto)
        if contexto.get("solicitud_id"):
            self.repo.actualizar_solicitud(contexto["solicitud_id"], EstadoSolicitud.CHECKOUT_PREPARADO)
        self.repo.registrar_auditoria(
            conversacion_id, "checkout_preparado", {"opcion_id": opcion_id, "cantidad": cantidad, "total": total}
        )
        await self.kapso.enviar_texto(
            telefono,
            "🎉 *Pedido preparado* ✅\n\n"
            f"🍔 {cantidad} x {opcion['producto_nombre']}\n"
            f"💰 Total: *${total:,} COP*\n\n"
            "Tu solicitud fue enviada para revision corporativa.\n"
            "🛒 Tu pedido queda listo en el carrito de Rappi.\n\n"
            "Escribe cuando quieras hacer otro pedido 🍽️",
        )
