#!/bin/bash
# Arranque del agente de compras.
#
#   ./start.sh           -> TODO LOCAL: rappi + backend local + tunnel + webhook Kapso
#   ./start.sh --hybrid  -> HIBRIDO: rappi + tunnel de rappi; backend corre en Railway
#                           (actualiza RAPPI_API_BASE_URL en Railway con la URL del tunnel)
#
set -e
cd "$(dirname "$0")"

MODO="${1:-local}"
if [ "$MODO" != "local" ] && [ "$MODO" != "--hybrid" ]; then
  echo "Uso: ./start.sh [local|--hybrid]"
  exit 1
fi
if [ "$MODO" == "--hybrid" ]; then MODO="hybrid"; fi

export PATH="$HOME/.bun/bin:$PATH"
LOGDIR=/tmp/agente
mkdir -p $LOGDIR

echo "== 1/4 Rappi CLI server (:3100) =="
if lsof -iTCP:3100 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "ya corriendo"
else
  bun run "$HOME/.bun/install/global/node_modules/@crafter/rappi-cli/server.ts" > $LOGDIR/rappi.log 2>&1 &
  sleep 3
fi
curl -s -o /dev/null -w "rappi: %{http_code}\n" "http://127.0.0.1:3100/api/cart"

BACKEND_URL=""
if [ "$MODO" == "local" ]; then
  echo "== 2/4 Backend FastAPI local (:8000) =="
  if lsof -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
    echo "ya corriendo"
  else
    .venv/bin/python -m uvicorn app.main:app --port 8000 > $LOGDIR/backend.log 2>&1 &
    sleep 3
  fi
  curl -s http://127.0.0.1:8000/health | head -c 120; echo
else
  BACKEND_URL=$(railway status 2>/dev/null | grep -o 'https://[a-z0-9.-]*railway.app' | head -1)
  echo "== 2/4 Backend en Railway: $BACKEND_URL =="
  curl -s -o /dev/null -w "backend railway: %{http_code}\n" "$BACKEND_URL/health"
fi

echo "== 3/4 Tunnel(es) Cloudflare =="
TUNNEL_BACKEND=""
if [ "$MODO" == "local" ]; then
  if pgrep -f "cloudflared tunnel --url http://localhost:8000" >/dev/null 2>&1; then
    echo "tunnel backend: ya corriendo"
  else
    cloudflared tunnel --url http://localhost:8000 > $LOGDIR/tunnel_backend.log 2>&1 &
    sleep 8
  fi
  TUNNEL_BACKEND=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' $LOGDIR/tunnel_backend.log | head -1)
  echo "tunnel backend: $TUNNEL_BACKEND"
  curl -s -o /dev/null -w "tunnel backend: %{http_code}\n" "$TUNNEL_BACKEND/health"
fi

if pgrep -f "cloudflared tunnel --url http://localhost:3100" >/dev/null 2>&1; then
  echo "tunnel rappi: ya corriendo"
else
  cloudflared tunnel --url http://localhost:3100 > $LOGDIR/tunnel_rappi.log 2>&1 &
  sleep 8
fi
TUNNEL_RAPPI=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' $LOGDIR/tunnel_rappi.log | head -1)
echo "tunnel rappi: $TUNNEL_RAPPI"
# Esperar a que el tunnel este vivo (hasta ~30s)
for i in $(seq 1 6); do
  CODIGO=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$TUNNEL_RAPPI/api/cart" || true)
  [ "$CODIGO" = "200" ] && break
  echo "tunnel rappi no responde ($CODIGO), reintento $i/6..."
  sleep 5
done
echo "tunnel rappi: $CODIGO"

echo "== 4/4 Webhook / variables =="
KAPSO_KEY=$(grep '^KAPSO_API_KEY=' .env | cut -d= -f2)
PHONE_ID=$(grep '^KAPSO_PHONE_NUMBER_ID=' .env | cut -d= -f2)
WEBHOOK_ID=$(curl -s -H "X-API-Key: $KAPSO_KEY" "https://api.kapso.ai/platform/v1/whatsapp/webhooks" | python3 -c "import json,sys; d=json.load(sys.stdin)['data']; print(d[0]['id'] if d else '')")

URL_OBJETIVO="$TUNNEL_BACKEND"
if [ "$MODO" == "hybrid" ]; then URL_OBJETIVO="$BACKEND_URL"; fi

if [ -z "$WEBHOOK_ID" ]; then
  echo "no hay webhook; creando..."
  SEC=$(grep '^KAPSO_WEBHOOK_SECRET=' .env | cut -d= -f2)
  curl -s -X POST "https://api.kapso.ai/platform/v1/whatsapp/phone_numbers/$PHONE_ID/webhooks" \
    -H "X-API-Key: $KAPSO_KEY" -H "Content-Type: application/json" \
    -d "{\"whatsapp_webhook\":{\"url\":\"$URL_OBJETIVO/webhooks/kapso\",\"secret_key\":\"$SEC\",\"events\":[\"whatsapp.message.received\"],\"active\":true}}" | head -c 150
elif [ "$MODO" == "hybrid" ]; then
  URL_ACTUAL=$(curl -s -H "X-API-Key: $KAPSO_KEY" "https://api.kapso.ai/platform/v1/whatsapp/webhooks" | python3 -c "import json,sys; d=json.load(sys.stdin)['data']; print(d[0]['url'] if d else '')")
  if [ "$URL_ACTUAL" != "$URL_OBJETIVO/webhooks/kapso" ]; then
    curl -s -X PUT "https://api.kapso.ai/platform/v1/whatsapp/phone_numbers/$PHONE_ID/webhooks/$WEBHOOK_ID" \
      -H "X-API-Key: $KAPSO_KEY" -H "Content-Type: application/json" \
      -d "{\"whatsapp_webhook\":{\"url\":\"$URL_OBJETIVO/webhooks/kapso\"}}" | head -c 150
  else
    echo "webhook Kapso ya apunta a Railway"
  fi
else
  curl -s -X PUT "https://api.kapso.ai/platform/v1/whatsapp/phone_numbers/$PHONE_ID/webhooks/$WEBHOOK_ID" \
    -H "X-API-Key: $KAPSO_KEY" -H "Content-Type: application/json" \
    -d "{\"whatsapp_webhook\":{\"url\":\"$URL_OBJETIVO/webhooks/kapso\"}}" | head -c 150
fi
echo

if [ "$MODO" == "hybrid" ]; then
  ACTUAL=$(railway variables --service backend --json 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('RAPPI_API_BASE_URL',''))" 2>/dev/null || echo "")
  if [ "$ACTUAL" != "$TUNNEL_RAPPI" ]; then
    railway variables --service backend --set "RAPPI_API_BASE_URL=$TUNNEL_RAPPI" 2>&1 | tail -1
    railway redeploy --service backend --yes 2>&1 | tail -1
  else
    echo "RAPPI_API_BASE_URL en Railway ya apunta al tunnel actual"
  fi
  echo "== Listo (HIBRIDO). Kapso -> Railway | Railway -> $TUNNEL_RAPPI =="
else
  echo "== Listo (LOCAL). Webhook Kapso -> $TUNNEL_BACKEND =="
fi
