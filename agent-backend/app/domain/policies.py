"""Validacion de presupuesto del pedido.

Unica regla: el TOTAL del pedido (precio unitario x cantidad de personas)
no puede superar el presupuesto maximo declarado por el empleado en su
mensaje. Si el empleado no declaro presupuesto, no hay tope.

Las politicas corporativas adicionales viven en otro sistema y llegan al
backend solo como contexto para Jev; el backend ya no aplica topes propios.
"""
from app.models.purchase import Decision, OpcionProducto, ResultadoEvaluacion


def validar_presupuesto(
    opcion: OpcionProducto,
    presupuesto_maximo_cop: int | None,
    cantidad: int = 1,
) -> ResultadoEvaluacion:
    """Valida que el total del pedido quepa en el presupuesto declarado."""
    cantidad = max(1, int(cantidad or 1))
    total = opcion.precio_cop * cantidad
    if presupuesto_maximo_cop is None:
        return ResultadoEvaluacion(
            opcion_id=opcion.opcion_id,
            decision=Decision.APROBAR,
            motivo=f"Sin presupuesto declarado; total estimado ${total:,} COP",
        )
    if total > presupuesto_maximo_cop:
        exceso = total - presupuesto_maximo_cop
        return ResultadoEvaluacion(
            opcion_id=opcion.opcion_id,
            decision=Decision.RECHAZAR,
            motivo=(
                f"Total ${total:,} COP ({cantidad} x ${opcion.precio_cop:,}) "
                f"supera el presupuesto de ${presupuesto_maximo_cop:,} COP en ${exceso:,}"
            ),
        )
    return ResultadoEvaluacion(
        opcion_id=opcion.opcion_id,
        decision=Decision.APROBAR,
        motivo=(
            f"Total ${total:,} COP ({cantidad} x ${opcion.precio_cop:,}) "
            f"dentro del presupuesto de ${presupuesto_maximo_cop:,} COP"
        ),
    )


def filtrar_por_presupuesto(
    opciones: list[OpcionProducto],
    presupuesto_maximo_cop: int | None,
    cantidad: int = 1,
) -> list[ResultadoEvaluacion]:
    """Evalua cada opcion contra el presupuesto; conserva el orden de entrada."""
    return [validar_presupuesto(o, presupuesto_maximo_cop, cantidad) for o in opciones]


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
