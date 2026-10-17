"""Politicas duras de gasto corporativo.

El backend aplica estas restricciones de forma obligatoria. Jev emite una
recomendacion, pero NINGUNA opcion que viole una regla dura puede aprobarse,
y la aceptacion del empleado nunca sustituye la aprobacion corporativa.
"""
from dataclasses import dataclass

from app.config import Settings
from app.models.purchase import Decision, OpcionProducto, ResultadoEvaluacion


@dataclass
class ContextoGasto:
    """Gasto acumulado del empleado para el dia en curso."""

    gasto_diario_cop: int = 0


def validar_limites_duros(
    opcion: OpcionProducto,
    contexto: ContextoGasto,
    settings: Settings,
) -> ResultadoEvaluacion:
    """Evalua las reglas obligatorias contra una opcion candidata."""
    violaciones: list[str] = []

    if opcion.precio_cop > settings.policy_max_order_cop:
        violaciones.append(
            f"precio {opcion.precio_cop} COP supera el maximo por pedido ({settings.policy_max_order_cop} COP)"
        )
    total_con_pedido = contexto.gasto_diario_cop + opcion.precio_cop
    if total_con_pedido > settings.policy_max_daily_cop:
        violaciones.append(
            f"total diario {total_con_pedido} COP superaria el maximo diario ({settings.policy_max_daily_cop} COP)"
        )

    decision = Decision.RECHAZAR if violaciones else Decision.APROBAR
    motivo = "Dentro de politicas" if not violaciones else "Viola politicas obligatorias: " + "; ".join(violaciones)
    return ResultadoEvaluacion(
        opcion_id=opcion.opcion_id,
        decision=decision,
        motivo=motivo,
        violaciones_politica=violaciones,
    )


def filtrar_aprobables(
    opciones: list[OpcionProducto],
    contexto: ContextoGasto,
    settings: Settings,
) -> list[ResultadoEvaluacion]:
    """Valida cada opcion contra las reglas duras y conserva el orden."""
    return [validar_limites_duros(opcion, contexto, settings) for opcion in opciones]


def mejores_opciones(
    evaluaciones: list[ResultadoEvaluacion],
    opciones_por_id: dict[str, OpcionProducto],
    cantidad: int = 3,
) -> list[OpcionProducto]:
    """Devuelve las primeras opciones aprobadas, hasta un limite."""
    resultado: list[OpcionProducto] = []
    for evaluacion in evaluaciones:
        if evaluacion.decision == Decision.APROBAR:
            opcion = opciones_por_id.get(evaluacion.opcion_id)
            if opcion is not None:
                resultado.append(opcion)
        if len(resultado) >= cantidad:
            break
    return resultado
