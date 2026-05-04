#!/bin/bash
# demo_data.sh — Peuple le lab avec des données réalistes pour la démonstration

BASTION="http://localhost:5002"
ROTATION="http://localhost:5003"
BK="dev-bastion-key-change-me"

H="-H 'X-API-Key: $BK' -H 'Content-Type: application/json'"

create_session() {
    local user=$1 target=$2 reason=$3 duration=$4
    curl -s -X POST "$BASTION/sessions" \
        -H "X-API-Key: $BK" -H "Content-Type: application/json" \
        -d "{\"user\":\"$user\",\"target\":\"$target\",\"reason\":\"$reason\",\"duration_minutes\":$duration}" \
        | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('session_id','ERR'))"
}

exec_cmd() {
    local sid=$1 cmd=$2
    curl -s -X POST "$BASTION/sessions/$sid/exec" \
        -H "X-API-Key: $BK" -H "Content-Type: application/json" \
        -d "{\"command\":\"$cmd\"}" > /dev/null
}

close_session() {
    local sid=$1
    curl -s -X DELETE "$BASTION/sessions/$sid" \
        -H "X-API-Key: $BK" > /dev/null
}

echo "════════════════════════════════════════════════"
echo "   mini-PAM — Génération des données de démo"
echo "════════════════════════════════════════════════"
echo ""

# ── Session 1 : Incident prod résolu (closed_normal) ──────────────────────────
echo "→ Session 1 : Incident nginx résolu..."
S1=$(create_session "guillaume" "server-dev-01" "Incident P1 — restart nginx suite timeout applicatif" 60)
exec_cmd "$S1" "systemctl status nginx 2>/dev/null || echo 'nginx: checking..'"
exec_cmd "$S1" "ls /etc/nginx/ 2>/dev/null || ls /etc/"
exec_cmd "$S1" "whoami && uptime"
close_session "$S1"
echo "  ✓ Session fermée (closed_normal) — 3 commandes enregistrées"

# ── Session 2 : Audit de configuration (closed_normal) ────────────────────────
echo "→ Session 2 : Audit de configuration..."
S2=$(create_session "guillaume" "server-dev-01" "Audit mensuel configuration SSH et droits fichiers" 30)
exec_cmd "$S2" "cat /etc/ssh/sshd_config"
exec_cmd "$S2" "ls -la /etc/sudoers.d/"
exec_cmd "$S2" "id && groups"
exec_cmd "$S2" "last -5 2>/dev/null || echo 'no login history'"
close_session "$S2"
echo "  ✓ Session fermée (closed_normal) — 4 commandes enregistrées"

# ── Session 3 : Déploiement (closed_normal) ───────────────────────────────────
echo "→ Session 3 : Vérification post-déploiement..."
S3=$(create_session "admin_pam" "server-dev-01" "Vérification post-déploiement v2.4.1 — ticket DEV-892" 45)
exec_cmd "$S3" "df -h"
exec_cmd "$S3" "free -m"
exec_cmd "$S3" "hostname && cat /etc/hostname"
close_session "$S3"
echo "  ✓ Session fermée (closed_normal) — 3 commandes enregistrées"

# ── Session 4 : Timeout JIT (closed_timeout) ──────────────────────────────────
echo "→ Session 4 : Démonstration JIT timeout (1 minute)..."
S4=$(create_session "guillaume" "server-dev-01" "Test JIT — accès limité dans le temps" 1)
exec_cmd "$S4" "whoami"
exec_cmd "$S4" "date"
echo "  Attente expiration automatique (1 min)..."
until [ "$(curl -s -H "X-API-Key: $BK" "$BASTION/sessions/$S4" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])" 2>/dev/null)" = "closed_timeout" ]; do
    sleep 3
done
echo "  ✓ Session coupée automatiquement (closed_timeout)"

# ── Session 5 : Active (en cours) ────────────────────────────────────────────
echo "→ Session 5 : Session active (en cours)..."
S5=$(create_session "admin_pam" "server-dev-01" "Supervision continue — monitoring hebdomadaire" 120)
exec_cmd "$S5" "uptime"
echo "  ✓ Session active — sera visible sur le dashboard"

# ── Rotation ──────────────────────────────────────────────────────────────────
echo ""
echo "→ Déclenchement d'une rotation de mots de passe..."
curl -s -X POST "$ROTATION/rotate/force" > /dev/null
sleep 4
METRICS=$(curl -s "$ROTATION/metrics")
ROT_COUNT=$(echo "$METRICS" | python3 -c "import sys,json; print(json.load(sys.stdin)['rotation_count'])" 2>/dev/null)
echo "  ✓ Rotation effectuée — $ROT_COUNT rotation(s) au total"

echo ""
echo "════════════════════════════════════════════════"
echo "   Données de démo prêtes !"
echo "   → http://localhost:5000"
echo ""
echo "   Dashboard    : 1 session active, 4 terminées"
echo "   Audit        : 5 sessions dont 1 JIT timeout"
echo "   Rotation     : métriques visibles dans le dashboard"
echo "════════════════════════════════════════════════"
