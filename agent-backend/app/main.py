"""Punto de entrada de la aplicacion FastAPI."""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.logging_setup import setup_logging
from app.routers import health, kapso_webhook
from app.services.orchestrator import get_orquestador


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Arranque: valida config y logs. Apagado: cierra clientes."""
    setup_logging()
    faltantes = get_settings().validate_required()
    if faltantes:
        import structlog

        structlog.get_logger("arranque").warning("config_incompleta", faltantes=faltantes)
    yield
    await get_orquestador().cerrar()


app = FastAPI(
    title="Agente de Compras Corporativas",
    description="MVP: solicitudes de comida por WhatsApp con Rappi, Jev y politicas corporativas",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(kapso_webhook.router)
