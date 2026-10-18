# Agente de Compras Corporativas con IA

Agente de WhatsApp que recibe solicitudes de comida en lenguaje natural, busca opciones reales en Rappi, las filtra por el presupuesto del pedido y las presenta con fotos; al elegir una, prepara el carrito y el checkout (sin pago) e inserta la factura en el sistema pagador (blinka) para su revision corporativa.

## Estado

- Backend desplegado en **Railway**: `https://backend-production-695d.up.railway.app`
- `rappi server` corre **local** (Plan B hibrido): la sesion de Rappi vive en IP residencial y el token nunca sale de la maquina. El backend lo alcanza por tunnel de Cloudflare.
- Codigo en `github.com/juliancape/HACKATON30X-TOKENGATE-RETO-BLINKA-SERVICES` (rama `main`).

## Arquitectura

```
Empleado (WhatsApp)
   |
Kapso (webhook firmado HMAC, payload v2)
   |
FastAPI en Railway  --- Gemini (intencion + requisitos, JSON estructurado)
   |                 --- Jev / TypeSafe AI (solo filtro de calidad y ranking)
   |                 --- Supabase (conversaciones, solicitudes, decisiones, price_history)
   v
rappi server (local, :3100) --- Rappi real
   |
Checkout preparado (sin pago)
   |
INSERT en pagador_subjects (Supabase, org tokengate)
   |
Core de facturacion (externo): aprueba/rechaza via pagador_reviews
```

## Reglas de negocio

- **Unica regla dura del backend**: el TOTAL del pedido (precio unitario x cantidad de personas) no puede superar el presupuesto declarado en el mensaje. Presupuesto = total, no por cabeza. Las opciones presentadas ya vienen pre-filtradas por ese total.
- La seleccion del empleado **no** equivale a aprobacion corporativa: quien aprueba/rechaza/pide info es el core de facturacion via `pagador_reviews`.
- Jev **no** decide aprobaciones: marca opciones de baja calidad y aporta el motivo; el filtro de presupuesto es determinista del backend.
- Nunca se ejecuta `rappi place-order`.
- Si el empleado no declara presupuesto, se busca sin tope.

## Estructura

```
agent-backend/
  app/
    config.py              # configuracion por .env (pydantic-settings)
    logging_setup.py       # logs estructurados JSON (structlog)
    models/                # Pydantic: dominio de compra, webhooks Kapso
    domain/policies.py     # regla de presupuesto total
    services/              # kapso, gemini, rappi, supabase, jev, orquestador
    routers/               # /health y /webhooks/kapso
  flows/                   # WhatsApp Flow JSON (requiere numero de produccion)
  supabase/migrations/     # 0001 (agente) y 0002 (esquema pagador_* del core)
  tests/
  start.sh                 # arranque con dos modos
```

## Arranque

```bash
# TODO LOCAL (rappi + backend local + tunnel + webhook Kapso)
./start.sh

# HIBRIDO (rappi + tunnel de rappi local; backend en Railway)
./start.sh --hybrid
```

Ambos modos son idempotentes: reutilizan procesos ya vivos y solo actualizan
webhook/variables cuando la URL del tunnel cambia.

Prerequisitos: Bun (`bun add -g @crafter/rappi-cli`), `railway login`,
`cloudflared`, token de Rappi vigente (`rappi whoami`).

## Seguridad del webhook

Kapso firma cada webhook con HMAC SHA256 (`X-Webhook-Signature`) usando
`KAPSO_WEBHOOK_SECRET`. El endpoint verifica con comparacion timing-safe sobre
el body crudo y deduplica con `X-Idempotency-Key`.

## Sistema pagador (core de facturacion)

Esquema en `supabase/migrations/0002_mig.sql` (solo `pagador_*`):

- Nuestro backend inserta en `pagador_subjects` via `pagador_save_writes`
  (`kind: "purchase"`, `amount.amountMinor`, payload con opcion, carrito y
  checkout preview) + evento en `pagador_audit_events`. Ese es el fin de
  nuestro alcance.
- El core consume los subjects y registra su decision en `pagador_reviews`
  (`approved` / `rejected` / `info_requested`), append-only con triggers.
- `PAGADOR_ORG_ID=tokengate` en el `.env`.

## Contratos pendientes / limitaciones

- WhatsApp Flows: implementado tras feature flag (`KAPSO_FLOW_ID_REQUISITOS`),
  requiere numero de produccion (el sandbox de Kapso no soporta Flows).
- Un solo producto por pedido (N unidades del mismo). Carrito multi-producto
  por persona queda como mejora.
- Formulario interactivo: el MVP usa botones/listas + extraccion por LLM.

## Notas de seguridad

- El `.env` nunca se versiona (esta en `.gitignore` de raiz y del servicio).
- El historial de git fue purgado con filter-branch y verificado con secret
  scanning de GitHub (0 alertas).
- Rotar las API keys (Kapso, Gemini, Supabase, Jev) tras el hackathon es
  buena practica: estuvieron en commits locales aunque nunca en el remoto.
