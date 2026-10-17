# Agente de Compras Corporativas con IA (MVP)

Backend FastAPI que orquesta: WhatsApp (Kapso) -> LLM (Gemini) -> Rappi (rappi-cli) -> Supabase (historico + politicas) -> Jev (evaluacion) -> Core de facturacion.

## Estructura

```
agent-backend/
  app/
    config.py            # configuracion via .env (pydantic-settings)
    logging_setup.py     # logs estructurados (structlog, JSON)
    models/              # Pydantic: dominio de compra y webhooks Kapso
    domain/policies.py   # reglas duras obligatorias (backend siempre refuerza)
    services/            # kapso, gemini, rappi, supabase, jev, billing, orquestador
    routers/             # /health y /webhooks/kapso
  supabase/migrations/   # SQL del esquema (conversations, purchase_requests, decisions, price_history, policies, audit_events)
  tests/
```

## Flujo implementado (maquina de estados)

1. Empleado escribe su solicitud -> Gemini extrae requisitos -> se confirman por botones.
2. `req:buscar` -> Rappi busca -> politicas duras (tope por pedido, tope diario) -> Jev evalua con historico + politicas -> top 3 opciones por lista interactiva.
3. Empleado elige -> revalidacion obligatoria contra politicas -> agregar carrito -> preview checkout (sin pago) -> registro enviado al core de facturacion.
4. "Ninguna me convence" -> nueva vuelta de requisitos. Sin opciones aprobadas -> estado ESCALADA.

## Como correr

```bash
# 1. Backend
cd agent-backend
cp .env.example .env   # y completar las credenciales
uv sync
uv run pytest          # pruebas unitarias
uv run uvicorn app.main:app --port 8000

# 2. Rappi CLI (otra terminal)
bun add -g @crafter/rappi-cli
rappi login            # autenticacion manual una vez
rappi server           # REST API en http://127.0.0.1:3100

# 3. Exponer el webhook publicamente (ej: ngrok)
ngrok http 8000
# Configurar el webhook en Kapso apuntando a <url>/webhooks/kapso
# y pegar el mismo secreto en KAPSO_WEBHOOK_SECRET
```

## Seguridad del webhook

Kapso firma cada webhook con HMAC SHA256 (`X-Webhook-Signature`) usando `KAPSO_WEBHOOK_SECRET`. El endpoint verifica la firma con comparacion timing-safe sobre el body crudo y deduplica con `X-Idempotency-Key`.

## Contratos pendientes

- **Jev**: se asume `POST {JEV_BASE_URL}/evaluate` con `{solicitud, opciones, historico_precios, politicas}` devolviendo `{"evaluaciones": [...]}`. Ajustar cuando llegue la documentacion del servicio.
- **Core de facturacion**: se asume `POST {BILLING_CORE_BASE_URL}/purchase-records`. Ajustar con la doc final.
- **Rappi REST**: los paths (`/search`, `/cart/add`, `/checkout`) son aproximados; verificar contra el servidor real de rappi-cli y ajustar `rappi_client.py`.
- Formulario interactivo: el MVP usa botones/listas + extraccion por LLM. WhatsApp Flows nativo queda como mejora.

## Notas

- Jev NO puede aprobar una opcion que viole una regla dura; la aceptacion del empleado nunca sustituye la aprobacion corporativa.
- Nunca se ejecuta `rappi place-order`.
- Ejecutar `supabase/migrations/0001_init.sql` en el SQL Editor de Supabase antes de arrancar.
