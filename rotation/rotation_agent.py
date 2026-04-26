"""Rotation Agent — Automatic password rotation with SSH and vault integration."""

import json
import os
import secrets
import threading
import time
from datetime import datetime

import paramiko
import requests
from flask import Flask, jsonify

app = Flask(__name__)

VAULT_URL = os.environ["VAULT_URL"]
VAULT_API_KEY = os.environ["VAULT_API_KEY"]
POLICY_PATH = os.environ.get("POLICY_PATH", "/config/policy.json")
ROTATION_INTERVAL = int(os.environ.get("ROTATION_INTERVAL_SECONDS", "3600"))
TTL_THRESHOLD = float(os.environ.get("TTL_THRESHOLD_PCT", "0.20"))

_metrics = {
    "total_managed": 0,
    "rotation_count": 0,
    "failure_count": 0,
    "last_success": None,
    "last_failure": None,
    "expired_unrotated": [],
}


# ── Vault & Policy helpers ────────────────────────────────────────────────────

def vault_get(path: str):
    resp = requests.get(f"{VAULT_URL}{path}",
                        headers={"X-API-Key": VAULT_API_KEY, "X-Owner": "rotation"},
                        timeout=5)
    resp.raise_for_status()
    return resp.json()


def vault_rotate(name: str, new_value: str):
    requests.post(f"{VAULT_URL}/secrets/{name}/rotate",
                  headers={"X-API-Key": VAULT_API_KEY, "X-Owner": "rotation",
                           "Content-Type": "application/json"},
                  json={"new_value": new_value}, timeout=5).raise_for_status()


def load_policy() -> dict:
    with open(POLICY_PATH) as f:
        return json.load(f)


def find_target(secret_name: str, policy: dict) -> dict | None:
    """Reverse lookup : secret_name → target config."""
    for cfg in policy["targets"].values():
        if cfg["vault_secret"] == secret_name:
            return cfg
    return None


# ── Core rotation logic ───────────────────────────────────────────────────────

def rotate_secret(secret: dict, target_cfg: dict) -> bool:
    """
    Rotation en 3 étapes atomiques.
    Ordre critique : SSH target AVANT vault pour éviter le lockout.
    En cas d'échec SSH, l'ancien mot de passe est conservé dans le vault.
    """
    name = secret["name"]
    new_password = secrets.token_urlsafe(32)

    _log("rotation_start", name, target=target_cfg["host"])

    try:
        current = vault_get(f"/secrets/{name}")["value"]
    except Exception as e:
        _log("rotation_failed", name, step="vault_read", error=str(e))
        return False

    # Étape 1 : changer sur la machine cible
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(target_cfg["host"], port=target_cfg["port"],
                       username=target_cfg["ssh_user"], password=current,
                       allow_agent=False, look_for_keys=False, timeout=10)
        _, stdout, stderr = client.exec_command(
            f'echo "{target_cfg["ssh_user"]}:{new_password}" | sudo chpasswd', timeout=10)
        exit_code = stdout.channel.recv_exit_status()
        client.close()
        if exit_code != 0:
            raise RuntimeError(f"chpasswd exit {exit_code}: {stderr.read().decode()}")
    except Exception as e:
        _log("rotation_failed", name, step="ssh_chpasswd", error=str(e))
        return False  # vault non modifié — connexion toujours possible avec l'ancien mot de passe

    # Étape 2 : mettre à jour le vault seulement si le target a changé
    try:
        vault_rotate(name, new_password)
    except Exception as e:
        _log("rotation_failed", name, step="vault_update", error=str(e),
             warning="TARGET_CHANGED_VAULT_NOT_UPDATED_MANUAL_INTERVENTION_REQUIRED")
        return False

    _log("rotation_success", name)
    return True


def run_rotation_cycle():
    """Inspecte tous les secrets et tourne ceux dont le TTL restant < seuil."""
    try:
        secrets_list = vault_get("/secrets")
        policy = load_policy()
    except Exception as e:
        _log("cycle_error", "-", error=str(e))
        return

    now = datetime.utcnow()
    _metrics["expired_unrotated"] = []

    for secret in secrets_list:
        created = datetime.fromisoformat(secret["created_at"])
        expires = datetime.fromisoformat(secret["expires_at"])
        total_ttl = (expires - created).total_seconds()
        remaining = (expires - now).total_seconds()
        ttl_pct = remaining / total_ttl if total_ttl > 0 else 0

        if remaining <= 0:
            _metrics["expired_unrotated"].append(secret["name"])
            _log("secret_expired_alert", secret["name"])
            continue

        if ttl_pct < TTL_THRESHOLD:
            target_cfg = find_target(secret["name"], policy)
            if not target_cfg:
                continue
            success = rotate_secret(secret, target_cfg)
            ts = datetime.utcnow().isoformat()
            if success:
                _metrics["rotation_count"] += 1
                _metrics["last_success"] = ts
            else:
                _metrics["failure_count"] += 1
                _metrics["last_failure"] = ts

    _metrics["total_managed"] = len(secrets_list)


def _log(action: str, secret: str, **kwargs):
    print(json.dumps({"timestamp": datetime.utcnow().isoformat(),
                      "action": action, "secret": secret, **kwargs}), flush=True)


def rotation_loop():
    _log("agent_started", "-", interval=ROTATION_INTERVAL, threshold_pct=TTL_THRESHOLD)
    while True:
        run_rotation_cycle()
        time.sleep(ROTATION_INTERVAL)


# ── Flask endpoints ────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/metrics")
def metrics():
    return jsonify(_metrics)


@app.post("/rotate/force")
def force_rotation():
    """Déclenche une rotation immédiate — utile pour la démo."""
    threading.Thread(target=run_rotation_cycle, daemon=True).start()
    return jsonify({"status": "rotation_cycle_triggered"})


if __name__ == "__main__":
    threading.Thread(target=rotation_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=5003, debug=False)
