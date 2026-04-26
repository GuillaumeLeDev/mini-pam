#!/bin/bash
# Bootstrap : seed le vault avec les secrets initiaux pour démarrer le lab

set -e

VAULT_URL="${VAULT_URL:-http://localhost:5001}"
VAULT_API_KEY="${VAULT_API_KEY:?Variable VAULT_API_KEY non définie}"

echo "[setup] Attente du vault sur $VAULT_URL..."
until curl -sf "$VAULT_URL/health" > /dev/null 2>&1; do
    echo "[setup] Vault pas encore prêt, retry dans 2s..."
    sleep 2
done
echo "[setup] Vault disponible."

create_secret() {
    local name=$1
    local value=$2
    local owner=$3
    local ttl=${4:-48}

    RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$VAULT_URL/secrets" \
        -H "Content-Type: application/json" \
        -H "X-API-Key: $VAULT_API_KEY" \
        -d "{\"name\":\"$name\",\"value\":\"$value\",\"owner\":\"$owner\",\"expires_in_hours\":$ttl}")

    HTTP_CODE=$(echo "$RESPONSE" | tail -1)
    BODY=$(echo "$RESPONSE" | head -1)

    if [ "$HTTP_CODE" = "201" ]; then
        echo "[setup] ✓ Secret '$name' créé — expire dans ${ttl}h"
    elif [ "$HTTP_CODE" = "409" ]; then
        echo "[setup] ~ Secret '$name' existe déjà, ignoré"
    else
        echo "[setup] ✗ Erreur sur '$name' (HTTP $HTTP_CODE) : $BODY"
    fi
}

echo "[setup] Création des secrets initiaux..."

create_secret "target-dev-admin"  "DevAdmin2024!"  "system" 48
create_secret "target-prod-admin" "ProdAdmin2024!" "system" 24

echo "[setup] Terminé. Démarrer docker-compose up pour target-dev."
