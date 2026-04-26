#!/bin/bash
# simulate_attack.sh — 4 scénarios d'attaque pour démonstration PAM

VAULT="http://localhost:5001"
BASTION="http://localhost:5002"
VK="dev-api-key-change-me"
BK="dev-bastion-key-change-me"

PASS=0
FAIL=0

check() {
    local label=$1 expected=$2 actual=$3
    if [ "$actual" = "$expected" ]; then
        echo "  [BLOCKED] $label"
        ((PASS++))
    else
        echo "  [MISSED]  $label (attendu HTTP $expected, obtenu HTTP $actual)"
        ((FAIL++))
    fi
}

echo "════════════════════════════════════════════════"
echo "   mini-PAM — Simulation d'attaques"
echo "════════════════════════════════════════════════"
echo ""

# ── Scénario 1 : Escalade de privilèges via le bastion ────────────────────────
echo "Scénario 1 — Escalade de privilèges (ops_engineer → prod)"
CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASTION/sessions" \
  -H "X-API-Key: $BK" -H "Content-Type: application/json" \
  -d '{"user":"guillaume","target":"server-prod-01","reason":"tentative","duration_minutes":5}')
check "Accès prod refusé au rôle ops_engineer" "403" "$CODE"

CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASTION/sessions" \
  -H "X-API-Key: $BK" -H "Content-Type: application/json" \
  -d '{"user":"guillaume","target":"server-dev-01","duration_minutes":10}')
check "Accès refusé sans raison obligatoire" "400" "$CODE"

echo ""

# ── Scénario 2 : Contournement du bastion ─────────────────────────────────────
echo "Scénario 2 — Accès direct au vault (contournement du bastion)"
CODE=$(curl -s -o /dev/null -w "%{http_code}" "$VAULT/secrets/target-dev-admin")
check "Lecture vault sans authentification" "401" "$CODE"

CODE=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "X-API-Key: $VK" -H "X-Owner: attacker" \
  "$VAULT/secrets/target-dev-admin")
check "Lecture vault avec owner non autorisé" "403" "$CODE"

CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$VAULT/secrets" \
  -H "Content-Type: application/json" \
  -d '{"name":"backdoor","value":"pwned","owner":"attacker","expires_in_hours":9999}')
check "Création de secret sans authentification" "401" "$CODE"

echo ""

# ── Scénario 3 : Dépassement de la durée JIT ─────────────────────────────────
echo "Scénario 3 — Dépassement de la durée JIT (session forcée à 1 minute)"
SESSION=$(curl -s -X POST "$BASTION/sessions" \
  -H "X-API-Key: $BK" -H "Content-Type: application/json" \
  -d '{"user":"guillaume","target":"server-dev-01","reason":"test jit attack","duration_minutes":1}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('session_id',''))" 2>/dev/null)

if [ -z "$SESSION" ]; then
    echo "  [MISSED]  Impossible de créer la session de test"
    ((FAIL++))
else
    echo "  Session créée : ${SESSION:0:8}... (expire dans 1 min) — attente..."
    until [ "$(curl -s -H "X-API-Key: $BK" "$BASTION/sessions/$SESSION" \
      | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])" 2>/dev/null)" = "closed_timeout" ]; do
        sleep 3
    done
    CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASTION/sessions/$SESSION/exec" \
      -H "X-API-Key: $BK" -H "Content-Type: application/json" \
      -d '{"command":"cat /etc/passwd"}')
    check "Exec bloqué après expiration JIT" "410" "$CODE"
fi

echo ""

# ── Audit trail avant le brute force ─────────────────────────────────────────
echo "Audit trail vault (attaques enregistrées jusqu'ici) :"
curl -s -H "X-API-Key: $VK" "$VAULT/audit" \
  | python3 -c "
import sys, json
logs = json.load(sys.stdin)
denied = [l for l in logs if l['status'] in ('denied', 'not_found')][:6]
for l in denied:
    print(f'  {l[\"timestamp\"][11:19]} | {l[\"action\"]:12} | {l[\"actor\"]:10} | {l[\"status\"]}')
print(f'  → {len(denied)} tentatives refusées loggées')
"

echo ""

# ── Scénario 4 : Brute force ─────────────────────────────────────────────────
echo "Scénario 4 — Brute force sur l'API vault (rate limiting)"
echo "  5 tentatives avec clés incorrectes..."
for i in 1 2 3 4 5; do
    curl -s -o /dev/null "$VAULT/secrets" -H "X-API-Key: wrong-key-$i"
done
CODE=$(curl -s -o /dev/null -w "%{http_code}" "$VAULT/secrets" -H "X-API-Key: wrong-key-6")
check "Rate limiting déclenché après 5 échecs (HTTP 429)" "429" "$CODE"
echo "  IP bloquée 60s — toutes les tentatives sont dans l'audit vault"

echo ""
echo "════════════════════════════════════════════════"
printf "   Résultat : %d bloqué(s)  |  %d manqué(s)\n" "$PASS" "$FAIL"
echo "════════════════════════════════════════════════"

[ "$FAIL" -eq 0 ]
