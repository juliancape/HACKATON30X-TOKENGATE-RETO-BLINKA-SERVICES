"""Pruebas de las reglas de negocio (politicas duras)."""
import pytest

from app.config import Settings
from app.domain.policies import ContextoGasto, filtrar_aprobables, mejores_opciones, validar_limites_duros
from app.models.purchase import Decision, OpcionProducto


@pytest.fixture
def settings() -> Settings:
    return Settings(
        kapso_api_key="x",
        kapso_phone_number_id="x",
        gemini_api_key="x",
        supabase_url="http://localhost",
        supabase_service_key="x",
        policy_max_order_cop=60000,
        policy_max_daily_cop=120000,
    )


def opcion(precio: int, nombre: str = "almojabana") -> OpcionProducto:
    return OpcionProducto(
        opcion_id=f"op_{nombre}_{precio}",
        tienda_id="t1",
        tienda_nombre="Tienda",
        producto_id="p1",
        producto_nombre=nombre,
        precio_cop=precio,
    )


def test_precio_dentro_de_politica_aprueba(settings: Settings) -> None:
    resultado = validar_limites_duros(opcion(30000), ContextoGasto(0), settings)
    assert resultado.decision == Decision.APROBAR


def test_precio_supera_maximo_por_pedido_rechaza(settings: Settings) -> None:
    resultado = validar_limites_duros(opcion(70000), ContextoGasto(0), settings)
    assert resultado.decision == Decision.RECHAZAR
    assert "maximo por pedido" in resultado.motivo


def test_gasto_diario_acumulado_rechaza(settings: Settings) -> None:
    resultado = validar_limites_duros(opcion(30000), ContextoGasto(gasto_diario_cop=100000), settings)
    assert resultado.decision == Decision.RECHAZAR
    assert "maximo diario" in resultado.motivo


def test_borde_exacto_maximo_aprueba(settings: Settings) -> None:
    resultado = validar_limites_duros(opcion(60000), ContextoGasto(0), settings)
    assert resultado.decision == Decision.APROBAR


def test_filtrar_aprobables_conserva_orden(settings: Settings) -> None:
    evaluaciones = filtrar_aprobables(
        [opcion(70000), opcion(20000), opcion(50000)], ContextoGasto(0), settings
    )
    assert [e.decision for e in evaluaciones] == [Decision.RECHAZAR, Decision.APROBAR, Decision.APROBAR]


def test_mejores_opciones_devuelve_maximo_tres(settings: Settings) -> None:
    opciones = [opcion(1000 * i, f"p{i}") for i in range(1, 6)]
    evaluaciones = filtrar_aprobables(opciones, ContextoGasto(0), settings)
    por_id = {o.opcion_id: o for o in opciones}
    seleccion = mejores_opciones(evaluaciones, por_id, cantidad=3)
    assert len(seleccion) == 3
    assert all(o.precio_cop <= 60000 for o in seleccion)
