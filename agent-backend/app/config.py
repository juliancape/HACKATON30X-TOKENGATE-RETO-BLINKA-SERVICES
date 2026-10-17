"""Configuracion central del backend via variables de entorno."""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Todas las credenciales y configuracion del servicio."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Aplicacion
    app_env: str = Field(default="dev")
    log_level: str = Field(default="INFO")

    # Kapso (WhatsApp)
    kapso_api_key: str = Field(default="", description="API key de proyecto Kapso")
    kapso_base_url: str = Field(default="https://api.kapso.ai/meta/whatsapp")
    kapso_phone_number_id: str = Field(default="")
    kapso_webhook_secret: str = Field(default="", description="Secreto HMAC de webhooks Kapso")

    # Gemini (LLM)
    gemini_api_key: str = Field(default="")
    gemini_model: str = Field(default="gemini-3.8-flash")

    # Supabase
    supabase_url: str = Field(default="")
    supabase_service_key: str = Field(default="")

    # Rappi CLI (servidor REST local del CLI, puerto 3100)
    rappi_api_base_url: str = Field(default="http://127.0.0.1:3100")
    rappi_cli_timeout_s: int = Field(default=60)

    # Jev (TypeSafe AI) - evaluacion de opciones
    jev_api_key: str = Field(default="", description="API key de TypeSafe AI (console.typesafe.ai)")
    jev_base_url: str = Field(default="", description="Obsoleto: la API es fija (api.typesafe.ai)")

    # WhatsApp Flow de requisitos (requiere numero de produccion; vacio = deshabilitado)
    kapso_flow_id_requisitos: str = Field(default="")

    # Sistema pagador (core de facturacion, esquema pagador_*)
    pagador_org_id: str = Field(default="tokengate")

    def validate_required(self) -> list[str]:
        """Devuelve la lista de variables obligatorias que faltan."""
        faltantes: list[str] = []
        if not self.kapso_api_key:
            faltantes.append("KAPSO_API_KEY")
        if not self.kapso_phone_number_id:
            faltantes.append("KAPSO_PHONE_NUMBER_ID")
        if not self.gemini_api_key:
            faltantes.append("GEMINI_API_KEY")
        if not self.supabase_url:
            faltantes.append("SUPABASE_URL")
        if not self.supabase_service_key:
            faltantes.append("SUPABASE_SERVICE_KEY")
        return faltantes


@lru_cache
def get_settings() -> Settings:
    """Instancia cacheada de la configuracion."""
    return Settings()
