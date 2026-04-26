"""Bastion — Jump Server with session recording and JIT access control."""

import fnmatch
import json
import os
import threading
import uuid
from datetime import datetime
from functools import wraps

import paramiko
import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

VAULT_URL = os.environ["VAULT_URL"]
VAULT_API_KEY = os.environ["VAULT_API_KEY"]
BASTION_API_KEY = os.environ["BASTION_API_KEY"]
POLICY_PATH = os.environ.get("POLICY_PATH", "/config/policy.json")
LOG_PATH = os.environ.get("LOG_PATH", "/data/sessions.log")

# In-memory stores — SSH clients et timers ne se sérialisent pas
_sessions: dict = {}
_ssh_clients: dict = {}
_timers: dict = {}


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_policy() -> dict:
    with open(POLICY_PATH) as f:
        return json.load(f)


def vault_get_secret(secret_name: str) -> str:
    """Récupère le secret déchiffré depuis le vault. L'humain ne le voit jamais."""
    resp = requests.get(
        f"{VAULT_URL}/secrets/{secret_name}",
        headers={"X-API-Key": VAULT_API_KEY, "X-Owner": "bastion"},
        timeout=5,
    )
    resp.raise_for_status()
    return resp.json()["value"]


def check_policy(user: str, target: str, duration: int, policy: dict) -> tuple[bool, str]:
    """Vérifie rôle, liste des targets autorisées et durée max."""
    user_cfg = policy["users"].get(user)
    if not user_cfg:
        return False, f"User '{user}' not in policy"

    target_cfg = policy["targets"].get(target)
    if not target_cfg:
        return False, f"Target '{target}' not in policy"

    if user_cfg["role"] not in target_cfg["allowed_roles"]:
        return False, f"Role '{user_cfg['role']}' not allowed on '{target}'"

    if duration > user_cfg["max_session_minutes"]:
        return False, f"Duration {duration}min > max {user_cfg['max_session_minutes']}min"

    allowed = user_cfg["allowed_targets"]
    if "*" not in allowed and not any(fnmatch.fnmatch(target, p) for p in allowed):
        return False, f"Target '{target}' not in user's allowed list"

    return True, "ok"


def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.headers.get("X-API-Key") != BASTION_API_KEY:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


def log_session(session: dict):
    """Persiste un snapshot de session en JSON lines."""
    log_dir = os.path.dirname(LOG_PATH)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(session) + "\n")


def close_session(session_id: str, status: str = "closed_normal"):
    """Ferme la connexion SSH et marque la session comme terminée (appelé par timer JIT ou API)."""
    session = _sessions.get(session_id)
    if not session or session["status"] != "active":
        return
    session["end"] = datetime.utcnow().isoformat()
    session["status"] = status

    client = _ssh_clients.pop(session_id, None)
    if client:
        client.close()

    timer = _timers.pop(session_id, None)
    if timer:
        timer.cancel()

    log_session(session)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    active = sum(1 for s in _sessions.values() if s["status"] == "active")
    return jsonify({"status": "ok", "active_sessions": active})


@app.post("/sessions")
@require_api_key
def create_session():
    data = request.get_json(silent=True) or {}
    user = data.get("user")
    target = data.get("target")
    reason = data.get("reason", "")
    duration = int(data.get("duration_minutes", 30))

    if not all([user, target]):
        return jsonify({"error": "user and target required"}), 400

    policy = load_policy()

    if policy["users"].get(user, {}).get("require_reason") and not reason:
        return jsonify({"error": "reason required for this user"}), 400

    allowed, msg = check_policy(user, target, duration, policy)
    if not allowed:
        return jsonify({"error": msg, "access": "denied"}), 403

    target_cfg = policy["targets"][target]

    try:
        password = vault_get_secret(target_cfg["vault_secret"])
    except Exception as e:
        return jsonify({"error": f"vault error: {e}"}), 503

    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            target_cfg["host"], port=target_cfg["port"],
            username=target_cfg["ssh_user"], password=password,
            allow_agent=False, look_for_keys=False, timeout=10,
        )
    except Exception as e:
        return jsonify({"error": f"SSH failed: {e}"}), 502

    session_id = str(uuid.uuid4())
    session = {
        "session_id": session_id,
        "user": user,
        "target": target,
        "reason": reason,
        "duration_minutes": duration,
        "start": datetime.utcnow().isoformat(),
        "end": None,
        "commands": [],
        "status": "active",
    }
    _sessions[session_id] = session
    _ssh_clients[session_id] = client

    # JIT : fermeture automatique après duration_minutes
    timer = threading.Timer(duration * 60, close_session, args=[session_id, "closed_timeout"])
    timer.daemon = True
    timer.start()
    _timers[session_id] = timer

    log_session(session)
    return jsonify({"session_id": session_id, "expires_in_minutes": duration}), 201


@app.post("/sessions/<session_id>/exec")
@require_api_key
def exec_command(session_id):
    data = request.get_json(silent=True) or {}
    command = data.get("command", "").strip()

    session = _sessions.get(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404
    if session["status"] != "active":
        return jsonify({"error": "Session is closed", "status": session["status"]}), 410

    client = _ssh_clients.get(session_id)
    if not client:
        close_session(session_id, "closed_error")
        return jsonify({"error": "SSH connection lost"}), 503

    try:
        _, stdout, stderr = client.exec_command(command, timeout=30)
        out = stdout.read().decode()
        err = stderr.read().decode()
    except Exception as e:
        close_session(session_id, "closed_error")
        return jsonify({"error": str(e)}), 502

    session["commands"].append(command)
    log_session(session)
    return jsonify({"command": command, "stdout": out, "stderr": err})


@app.get("/sessions")
@require_api_key
def list_sessions():
    return jsonify(list(_sessions.values()))


@app.get("/sessions/<session_id>")
@require_api_key
def get_session_detail(session_id):
    session = _sessions.get(session_id)
    if not session:
        return jsonify({"error": "Not found"}), 404
    return jsonify(session)


@app.delete("/sessions/<session_id>")
@require_api_key
def close_session_endpoint(session_id):
    if session_id not in _sessions:
        return jsonify({"error": "Not found"}), 404
    close_session(session_id, "closed_normal")
    return jsonify({"session_id": session_id, "status": "closed"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002, debug=False)
