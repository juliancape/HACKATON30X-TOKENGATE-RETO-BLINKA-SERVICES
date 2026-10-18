#!/bin/bash
# Levanta todo el stack local del agente de compras y actualiza el webhook de Kapso
# con la URL nueva del tunnel. Uso: ./start.sh
set -e
cd "$(dirname "$0")"

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

echo "== 2/4 Backend FastAPI (:8000) =="
if lsof -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "ya corriendo"
else
  .venv/bin/python -m uvicorn app.main:app --port 8000 > $LOGDIR/backend.log 2>&1 &
  sleep 3
fi
curl -s http://127.0.0.1:8000/health | head -c 120; echo

echo "== 3/4 Tunnel Cloudflare =="
if pgrep -f "cloudflared tunnel" >/dev/null 2>&1; then
  echo "ya corriendo"
else
  cloudflared tunnel --url http://localhost:8000 > $LOGDIR/tunnel.log 2>&1 &
  sleep 8
fi
TUNNEL_URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' $LOGDIR/tunnel.log | head -1)
echo "tunnel: $TUNNEL_URL"
curl -s -o /dev/null -w "tunnel: %{http_code}\n" "$TUNNEL_URL/health"

echo "== 4/4 Actualizar webhook en Kapso =="
KAPSO_KEY=$(grep '^KAPSO_API_KEY=' .env | cut -d= -f2)
PHONE_ID=$(grep '^KAPSO_PHONE_NUMBER_ID=' .env | cut -d= -f2)
WEBHOOK_ID=$(curl -s -H "X-API-Key: $KAPSO_KEY" "https://api.kapso.ai/platform/v1/whatsapp/webhooks" | python3 -c "import json,sys; d=json.load(sys.stdin)['data']; print(d[0]['id'] if d else '')")
if [ -z "$WEBHOOK_ID" ]; then
  echo "no hay webhook creado; creando..."
  SEC=$(grep '^KAPSO_WEBHOOK_SECRET=' .env | cut -d= -f2)
  curl -s -X POST "https://api.kapso.ai/platform/v1/whatsapp/phone_numbers/$PHONE_ID/webhooks" \
    -H "X-API-Key: $KAPSO_KEY" -H "Content-Type: application/json" \
    -d "{\"whatsapp_webhook\":{\"url\":\"$TUNNEL_URL/webhooks/kapso\",\"secret_key\":\"$SEC\",\"events\":[\"whatsapp.message.received\"],\"active\":true}}" | head -c 200
else
  curl -s -X PUT "https://api.kapso.ai/platform/v1/whatsapp/phone_numbers/$PHONE_ID/webhooks/$WEBHOOK_ID" \
    -H "X-API-Key: $KAPSO_KEY" -H "Content-Type: application/json" \
    -d "{\"whatsapp_webhook\":{\"url\":\"$TUNNEL_URL/webhooks/kapso\"}}" | head -c 200
fi
echo
echo "== Listo. Todo arriba =="
