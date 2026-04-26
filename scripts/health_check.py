"""Health check — vérifie que tous les composants du lab PAM sont opérationnels."""

import os
import sys

import requests

VAULT_URL    = os.environ.get("VAULT_URL",    "http://localhost:5001")
BASTION_URL  = os.environ.get("BASTION_URL",  "http://localhost:5002")
ROTATION_URL = os.environ.get("ROTATION_URL", "http://localhost:5003")
PORTAL_URL   = os.environ.get("PORTAL_URL",   "http://localhost:5000")
VAULT_API_KEY    = os.environ.get("VAULT_API_KEY",    "dev-api-key-change-me")
BASTION_API_KEY  = os.environ.get("BASTION_API_KEY",  "dev-bastion-key-change-me")

VH = {"X-API-Key": VAULT_API_KEY, "X-Owner": "health_check"}
BH = {"X-API-Key": BASTION_API_KEY}

results = []
all_ok = True


def check(label: str, fn):
    global all_ok
    try:
        fn()
        results.append(("ok", label))
    except Exception as e:
        results.append(("fail", f"{label} — {e}"))
        all_ok = False


# ── 1. Vault ──────────────────────────────────────────────────────────────────

check("Vault API répond",
      lambda: requests.get(f"{VAULT_URL}/health", timeout=3).raise_for_status())


def check_active_secret():
    r = requests.get(f"{VAULT_URL}/secrets", headers=VH, timeout=3)
    r.raise_for_status()
    active = [s for s in r.json() if s["status"] == "active"]
    if not active:
        raise RuntimeError("aucun secret actif en base")

check("Vault a au moins 1 secret actif", check_active_secret)

# ── 2. Bastion ────────────────────────────────────────────────────────────────

check("Bastion accessible",
      lambda: requests.get(f"{BASTION_URL}/health", timeout=3).raise_for_status())


def check_bastion_session():
    r = requests.post(f"{BASTION_URL}/sessions", headers={**BH, "Content-Type": "application/json"},
                      json={"user": "guillaume", "target": "server-dev-01",
                            "reason": "health_check", "duration_minutes": 1},
                      timeout=10)
    if r.status_code != 201:
        raise RuntimeError(f"création session échouée : {r.json().get('error')}")
    sid = r.json()["session_id"]
    requests.delete(f"{BASTION_URL}/sessions/{sid}", headers=BH, timeout=5)

check("target-dev joignable via bastion (SSH OK)", check_bastion_session)

# ── 3. Rotation ───────────────────────────────────────────────────────────────

def check_rotation():
    r = requests.get(f"{ROTATION_URL}/health", timeout=3)
    r.raise_for_status()
    m = requests.get(f"{ROTATION_URL}/metrics", timeout=3).json()
    if m.get("total_managed", 0) == 0:
        raise RuntimeError("aucun secret géré par l'agent de rotation")

check("Rotation agent opérationnel", check_rotation)

# ── 4. Portail ────────────────────────────────────────────────────────────────

check("Portail web accessible",
      lambda: requests.get(f"{PORTAL_URL}/", timeout=3).raise_for_status())

# ── Affichage ─────────────────────────────────────────────────────────────────

print("\nmini-PAM — Health Check")
print("─" * 45)
for status, label in results:
    icon = "✓" if status == "ok" else "✗"
    print(f"  {icon}  {label}")
print("─" * 45)

if all_ok:
    print("  STATUS : LAB OPÉRATIONNEL\n")
    sys.exit(0)
else:
    print("  STATUS : LAB DÉGRADÉ — vérifier les services en erreur\n")
    sys.exit(1)
