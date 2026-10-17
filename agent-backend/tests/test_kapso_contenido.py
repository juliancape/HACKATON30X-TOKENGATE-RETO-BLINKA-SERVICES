"""Pruebas del parseo de mensajes Kapso, incluyendo respuestas de WhatsApp Flow."""
from app.models.kapso import KapsoMessage, extraer_contenido


def test_texto_simple() -> None:
    m = KapsoMessage(id="1", type="text", text={"body": "quiero sushi"}, kapso={"direction": "inbound"})
    c = extraer_contenido(m)
    assert c.tipo == "texto"
    assert c.texto_libre == "quiero sushi"


def test_boton_lista() -> None:
    m = KapsoMessage(
        id="2",
        type="interactive",
        interactive={"type": "list_reply", "list_reply": {"id": "sel:123", "title": "Sushi"}},
        kapso={"direction": "inbound"},
    )
    c = extraer_contenido(m)
    assert c.tipo == "boton"
    assert c.boton_id == "sel:123"


def test_flow_response_desde_response_json() -> None:
    m = KapsoMessage(
        id="3",
        type="interactive",
        interactive={
            "type": "nfm_reply",
            "nfm_reply": {
                "name": "flow",
                "body": "Sent",
                "response_json": '{"descripcion":"sushi","presupuesto":"40000","personas":"2","restricciones":"sin picante"}',
            },
        },
        kapso={"direction": "inbound"},
    )
    c = extraer_contenido(m)
    assert c.tipo == "flow"
    assert c.flow_data is not None
    assert c.flow_data["descripcion"] == "sushi"
    assert c.flow_data["presupuesto"] == "40000"


def test_flow_response_desde_kapso_flow_response() -> None:
    m = KapsoMessage(
        id="4",
        type="interactive",
        interactive={"type": "nfm_reply", "nfm_reply": {"name": "flow", "body": "Sent"}},
        kapso={"direction": "inbound", "flow_response": {"descripcion": "pizza", "presupuesto": "30000"}},
    )
    c = extraer_contenido(m)
    assert c.tipo == "flow"
    assert c.flow_data == {"descripcion": "pizza", "presupuesto": "30000"}


def test_flow_response_malformado_da_vacio() -> None:
    m = KapsoMessage(
        id="5",
        type="interactive",
        interactive={"type": "nfm_reply", "nfm_reply": {"name": "flow", "response_json": "no-json"}},
        kapso={"direction": "inbound"},
    )
    c = extraer_contenido(m)
    assert c.tipo == "flow"
    assert c.flow_data == {}
