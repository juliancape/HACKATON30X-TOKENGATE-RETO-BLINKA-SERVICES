"""Modelos Pydantic del dominio de compras."""
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class EstadoSolicitud(str, Enum):
    """Estados del ciclo de vida de una solicitud de compra."""

    NUEVA = "nueva"
    RECOPILANDO_REQUISITOS = "recopilando_requisitos"
    BUSCANDO_OPCIONES = "buscando_opciones"
    ESPERANDO_SELECCION = "esperando_seleccion"
    CHECKOUT_PREPARADO = "checkout_preparado"
    ESCALADA = "escalada"
    RECHAZADA = "rechazada"
    COMPLETADA = "completada"
    ERROR = "error"


class Decision(str, Enum):
    """Decision de la evaluacion de politicas."""

    APROBAR = "aprobar"
    RECHAZAR = "rechazar"
    ESCALAR = "escalar"


class RequisitosCompra(BaseModel):
    """Requisitos recopilados del empleado para la busqueda."""

    descripcion: str = Field(description="Que desea comprar en lenguaje natural")
    presupuesto_maximo_cop: int | None = Field(default=None, gt=0)
    cantidad_personas: int = Field(default=1, ge=1)
    restricciones: list[str] = Field(default_factory=list, description="Restricciones: alergias, tipo de comida, etc.")


class OpcionProducto(BaseModel):
    """Opcion candidata de Rappi."""

    opcion_id: str
    tienda_id: str
    tienda_nombre: str
    producto_id: str
    producto_nombre: str
    precio_cop: int
    tiempo_entrega_min: int | None = None
    calificacion: float | None = None


class ResultadoEvaluacion(BaseModel):
    """Resultado estructurado de la evaluacion de una opcion (Jev + politicas duras)."""

    opcion_id: str
    decision: Decision
    motivo: str
    precio_historico_promedio_cop: int | None = None
    desviacion_pct: float | None = None
    violaciones_politica: list[str] = Field(default_factory=list)


class SolicitudCompra(BaseModel):
    """Registro de una solicitud de compra trazable."""

    solicitud_id: str
    conversacion_id: str
    telefono_empleado: str
    estado: EstadoSolicitud = EstadoSolicitud.NUEVA
    requisitos: RequisitosCompra | None = None
    creado_en: datetime | None = None
    actualizado_en: datetime | None = None
