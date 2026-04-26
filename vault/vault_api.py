"""Vault API — Secret Store with Fernet encryption and audit logging."""

import json
import os
import secrets
import sqlite3
from datetime import datetime, timedelta
from functools import wraps

from cryptography.fernet import Fernet
from flask import Flask, g, jsonify, request
from rate_limiter import is_blocked, record_failure

app = Flask(__name__)

VAULT_API_KEY = os.environ["VAULT_API_KEY"]
FERNET_KEY = os.environ["FERNET_KEY"].encode()
DB_PATH = os.environ.get("DB_PATH", "/data/secrets.db")
# Services internes autorisés à lire n'importe quel secret (bypass owner check)
TRUSTED_SERVICES = set(os.environ.get("TRUSTED_SERVICES", "bastion,rotation").split(","))

fernet = Fernet(FERNET_KEY)


# ── Database ──────────────────────────────────────────────────────────────────

def init_db():
    """Create tables on first run."""
    db = sqlite3.connect(DB_PATH)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS secrets (
            name        TEXT PRIMARY KEY,
            value_enc   TEXT NOT NULL,
            owner       TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            expires_at  TEXT NOT NULL,
            rotations   INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS audit_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT NOT NULL,
            action      TEXT NOT NULL,
            secret_name TEXT NOT NULL,
            actor       TEXT NOT NULL,
            ip          TEXT NOT NULL,
            status      TEXT NOT NULL
        );
    """)
    db.commit()
    db.close()


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_):
    db = g.pop("db", None)
    if db:
        db.close()


# ── Helpers ───────────────────────────────────────────────────────────────────

def log_access(action: str, secret_name: str, actor: str, ip: str, status: str):
    """Write structured audit entry to stdout and SQLite."""
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "action": action,
        "secret_name": secret_name,
        "actor": actor,
        "ip": ip,
        "status": status,
    }
    print(json.dumps(entry), flush=True)
    try:
        db = sqlite3.connect(DB_PATH)
        db.execute(
            "INSERT INTO audit_log (timestamp,action,secret_name,actor,ip,status) VALUES (?,?,?,?,?,?)",
            (entry["timestamp"], action, secret_name, actor, ip, status),
        )
        db.commit()
        db.close()
    except Exception:
        pass


def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        ip = request.remote_addr
        if is_blocked(ip):
            return jsonify({"error": "Too many failed attempts"}), 429
        if request.headers.get("X-API-Key") != VAULT_API_KEY:
            record_failure(ip)
            log_access("auth_failed", "-", "unknown", ip, "denied")
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/secrets")
@require_api_key
def create_secret():
    data = request.get_json(silent=True) or {}
    name = data.get("name")
    value = data.get("value")
    owner = data.get("owner")
    ttl_hours = int(data.get("expires_in_hours", 24))

    if not all([name, value, owner]):
        return jsonify({"error": "name, value, owner required"}), 400

    value_enc = fernet.encrypt(value.encode()).decode()
    now = datetime.utcnow()
    expires_at = (now + timedelta(hours=ttl_hours)).isoformat()

    try:
        get_db().execute(
            "INSERT INTO secrets (name,value_enc,owner,created_at,expires_at) VALUES (?,?,?,?,?)",
            (name, value_enc, owner, now.isoformat(), expires_at),
        )
        get_db().commit()
    except sqlite3.IntegrityError:
        return jsonify({"error": "Secret already exists"}), 409

    log_access("create", name, owner, request.remote_addr, "success")
    return jsonify({"name": name, "expires_at": expires_at}), 201


@app.get("/secrets")
@require_api_key
def list_secrets():
    now = datetime.utcnow()
    rows = get_db().execute(
        "SELECT name,owner,created_at,expires_at,rotations FROM secrets"
    ).fetchall()
    result = []
    for row in rows:
        status = "active" if datetime.fromisoformat(row["expires_at"]) > now else "expired"
        result.append({**dict(row), "status": status})
    return jsonify(result)


@app.get("/secrets/<name>")
@require_api_key
def get_secret(name):
    # X-Owner identifie le demandeur — dans un vrai PAM ce serait déduit du token d'auth
    actor = request.headers.get("X-Owner", "unknown")
    row = get_db().execute("SELECT * FROM secrets WHERE name=?", (name,)).fetchone()

    if not row:
        log_access("read", name, actor, request.remote_addr, "not_found")
        return jsonify({"error": "Not found"}), 404

    if datetime.fromisoformat(row["expires_at"]) < datetime.utcnow():
        log_access("read", name, actor, request.remote_addr, "expired")
        return jsonify({"error": "Secret expired"}), 410

    if row["owner"] != actor and actor not in TRUSTED_SERVICES:
        log_access("read", name, actor, request.remote_addr, "denied")
        return jsonify({"error": "Access denied"}), 403

    value = fernet.decrypt(row["value_enc"].encode()).decode()
    log_access("read", name, actor, request.remote_addr, "success")
    return jsonify({"name": name, "value": value, "expires_at": row["expires_at"]})


@app.post("/secrets/<name>/rotate")
@require_api_key
def rotate_secret(name):
    actor = request.headers.get("X-Owner", "unknown")
    data = request.get_json(silent=True) or {}
    row = get_db().execute("SELECT * FROM secrets WHERE name=?", (name,)).fetchone()

    if not row:
        return jsonify({"error": "Not found"}), 404

    new_value = data.get("new_value") or secrets.token_urlsafe(32)
    value_enc = fernet.encrypt(new_value.encode()).decode()
    expires_at = (datetime.utcnow() + timedelta(hours=24)).isoformat()

    get_db().execute(
        "UPDATE secrets SET value_enc=?,expires_at=?,rotations=rotations+1 WHERE name=?",
        (value_enc, expires_at, name),
    )
    get_db().commit()
    log_access("rotate", name, actor, request.remote_addr, "success")
    return jsonify({"name": name, "rotated": True, "expires_at": expires_at})


@app.get("/audit")
@require_api_key
def get_audit():
    rows = get_db().execute(
        "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT 200"
    ).fetchall()
    return jsonify([dict(row) for row in rows])


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5001, debug=False)
