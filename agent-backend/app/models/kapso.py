"""Modelos de los payloads de webhooks de Kapso (formato v2)."""
from pydantic import BaseModel, Field


class KapsoMessage(BaseModel):
    """Mensaje entrante dentro del webhook."""

    id: str
    timestamp: str | None = None
    type: str = "text"
    text: dict | None = None
    interactive: dict | None = None
    kapso: dict = Field(default_factory=dict)


class KapsoConversation(BaseModel):
    """Conversacion asociada al mensaje."""

    id: str
    contact_name: str | None = None
    phone_number: str | None = None
    phone_number_id: str | None = None


class KapsoWebhookPayload(BaseModel):
    """Payload de whatsapp.message.received (v2)."""

    message: KapsoMessage
    conversation: KapsoConversation
    phone_number_id: str | None = None
    is_new_conversation: bool = False


class TextoEntrante(BaseModel):
    """Normalizacion del contenido entrante relevante para el orquestador."""

    tipo: str
    texto_libre: str | None = None
    boton_id: str | None = None
    boton_titulo: str | None = None
    flow_data: dict | None = None


def extraer_contenido(mensaje: KapsoMessage) -> TextoEntrante:
    """Normaliza el mensaje entrante a texto libre, click de boton o respuesta de Flow."""
    if mensaje.type == "interactive" and mensaje.interactive:
        tipo_inter = mensaje.interactive.get("type", "")
        if tipo_inter == "button_reply":
            reply = mensaje.interactive.get("button_reply", {})
            return TextoEntrante(tipo="boton", boton_id=reply.get("id"), boton_titulo=reply.get("title"))
        if tipo_inter == "list_reply":
            reply = mensaje.interactive.get("list_reply", {})
            return TextoEntrante(tipo="boton", boton_id=reply.get("id"), boton_titulo=reply.get("title"))
        if tipo_inter == "nfm_reply":
            # Respuesta de un WhatsApp Flow completado
            nfm = mensaje.interactive.get("nfm_reply", {})
            datos: dict = {}
            crudo = nfm.get("response_json")
            if isinstance(crudo, str) and crudo:
                try:
                    import json

                    datos = json.loads(crudo)
                except ValueError:
                    datos = {}
            if not datos:
                datos = mensaje.kapso.get("flow_response") or {}
            return TextoEntrante(tipo="flow", flow_data=datos)
    if mensaje.type == "text" and mensaje.text:
        return TextoEntrante(tipo="texto", texto_libre=mensaje.text.get("body"))
    contenido = mensaje.kapso.get("content")
    if isinstance(contenido, str) and contenido:
        return TextoEntrante(tipo="texto", texto_libre=contenido)
    return TextoEntrante(tipo="otro")
