"""Pruebas de la regla de presupuesto total del pedido."""
from app.domain.policies import filtrar_por_presupuesto, mejores_opciones, validar_presupuesto
from app.models.purchase import Decision, OpcionProducto


def opcion(precio: int, nombre: str = "perro") -> OpcionProducto:
    return OpcionProducto(
        opcion_id=f"op_{nombre}_{precio}",
        tienda_id="t1",
        tienda_nombre="Tienda",
        producto_id="p1",
        producto_nombre=nombre,
        precio_cop=precio,
    )


def test_sin_presupuesto_aprueba() -> None:
    resultado = validar_presupuesto(opcion(50000), None, 1)
    assert resultado.decision == Decision.APROBAR


def test_una_persona_dentro_del_presupuesto() -> None:
    resultado = validar_presupuesto(opcion(35000), 50000, 1)
    assert resultado.decision == Decision.APROBAR


def test_dos_personas_total_supera_presupuesto_rechaza() -> None:
    # 35000 x 2 = 70000 > 50000: el caso exacto reportado
    resultado = validar_presupuesto(opcion(35000), 50000, 2)
    assert resultado.decision == Decision.RECHAZAR
    assert "supera el presupuesto" in resultado.motivo


def test_dos_personas_dentro_del_presupuesto() -> None:
    # 24000 x 2 = 48000 <= 50000
    resultado = validar_presupuesto(opcion(24000), 50000, 2)
    assert resultado.decision == Decision.APROBAR


def test_borde_exacto_aprueba() -> None:
    # 25000 x 2 = 50000 == presupuesto
    resultado = validar_presupuesto(opcion(25000), 50000, 2)
    assert resultado.decision == Decision.APROBAR


def test_filtro_conserva_orden_y_decide_por_total() -> None:
    evaluaciones = filtrar_por_presupuesto(
        [opcion(35000), opcion(24000), opcion(26000)], 50000, 2
    )
    assert [e.decision for e in evaluaciones] == [
        Decision.RECHAZAR,
        Decision.APROBAR,
        Decision.RECHAZAR,
    ]


def test_mejores_opciones_maximo_tres() -> None:
    opciones = [opcion(1000 * i, f"p{i}") for i in range(1, 6)]
    evaluaciones = filtrar_por_presupuesto(opciones, 50000, 1)
    por_id = {o.opcion_id: o for o in opciones}
    assert len(mejores_opciones(evaluaciones, por_id, cantidad=3)) == 3
