"""Routers de salud y verificacion de configuracion."""
from fastapi import APIRouter

from app.config import get_settings
from app.services.billing_client import BillingCoreClient
from app.services.jev_client import JevClient

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    """Estado del servicio y de las integraciones externas."""
    settings = get_settings()
    faltantes = settings.validate_required()
    return {
        "status": "ok" if not faltantes else "config_incompleta",
        "faltantes": faltantes,
        "integraciones": {
            "kapso": bool(settings.kapso_api_key and settings.kapso_phone_number_id),
            "gemini": bool(settings.gemini_api_key),
            "supabase": bool(settings.supabase_url and settings.supabase_service_key),
            "rappi": settings.rappi_api_base_url,
            "jev": JevClient().configurado,
            "billing_core": BillingCoreClient().configurado,
        },
    }
