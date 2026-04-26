"""Portal web — Interface for PAM access requests and audit."""

import csv
import io
import os

import requests
from flask import Flask, Response, render_template, request

app = Flask(__name__)

VAULT_URL = os.environ["VAULT_URL"]
VAULT_API_KEY = os.environ["VAULT_API_KEY"]
BASTION_URL = os.environ["BASTION_URL"]
BASTION_API_KEY = os.environ["BASTION_API_KEY"]
ROTATION_URL = os.environ.get("ROTATION_URL", "")
PORTAL_USER = os.environ.get("PORTAL_USER", "guillaume")

_VAULT_H = {"X-API-Key": VAULT_API_KEY, "X-Owner": PORTAL_USER}
_BASTION_H = {"X-API-Key": BASTION_API_KEY, "Content-Type": "application/json"}


def get_secrets():
    try:
        return requests.get(f"{VAULT_URL}/secrets", headers=_VAULT_H, timeout=3).json()
    except Exception:
        return []


def get_sessions():
    try:
        return requests.get(f"{BASTION_URL}/sessions", headers=_BASTION_H, timeout=3).json()
    except Exception:
        return []


def get_rotation_metrics():
    if not ROTATION_URL:
        return {}
    try:
        return requests.get(f"{ROTATION_URL}/metrics", timeout=3).json()
    except Exception:
        return {}


# ── Pages ─────────────────────────────────────────────────────────────────────

@app.get("/")
def dashboard():
    secrets = get_secrets()
    sessions = get_sessions()
    rotation = get_rotation_metrics()
    active_secrets = sum(1 for s in secrets if s["status"] == "active")
    expired_secrets = sum(1 for s in secrets if s["status"] == "expired")
    active_sessions = sum(1 for s in sessions if s["status"] == "active")
    recent = sorted(sessions, key=lambda s: s["start"], reverse=True)[:5]
    alerts = []
    if expired_secrets:
        alerts.append(f"{expired_secrets} secret(s) expirés non renouvelés")
    if rotation.get("expired_unrotated"):
        alerts.append(f"Rotation manquée : {', '.join(rotation['expired_unrotated'])}")
    return render_template("index.html", active_secrets=active_secrets,
                           expired_secrets=expired_secrets, active_sessions=active_sessions,
                           recent_sessions=recent, rotation=rotation,
                           alerts=alerts, user=PORTAL_USER)


@app.get("/checkout")
def checkout_form():
    return render_template("checkout.html", user=PORTAL_USER, result=None)


@app.post("/checkout")
def checkout_submit():
    target = request.form.get("target")
    reason = request.form.get("reason", "").strip()
    duration = int(request.form.get("duration", 30))
    try:
        resp = requests.post(f"{BASTION_URL}/sessions", headers=_BASTION_H,
                             json={"user": PORTAL_USER, "target": target,
                                   "reason": reason, "duration_minutes": duration},
                             timeout=10)
        data = resp.json()
        if resp.status_code == 201:
            result = {"success": True, "session_id": data["session_id"],
                      "expires_in": data["expires_in_minutes"]}
        else:
            result = {"success": False, "error": data.get("error", "Erreur inconnue")}
    except Exception as e:
        result = {"success": False, "error": str(e)}
    return render_template("checkout.html", user=PORTAL_USER, result=result)


@app.get("/sessions")
def audit_sessions():
    sessions = get_sessions()
    sessions = sorted(sessions, key=lambda s: s["start"], reverse=True)
    filter_user = request.args.get("user", "")
    filter_target = request.args.get("target", "")
    filter_status = request.args.get("status", "")
    if filter_user:
        sessions = [s for s in sessions if filter_user in s["user"]]
    if filter_target:
        sessions = [s for s in sessions if filter_target in s["target"]]
    if filter_status:
        sessions = [s for s in sessions if s["status"] == filter_status]
    return render_template("sessions.html", sessions=sessions,
                           filter_user=filter_user, filter_target=filter_target,
                           filter_status=filter_status)


@app.get("/sessions/export.csv")
def export_csv():
    sessions = get_sessions()
    output = io.StringIO()
    fields = ["session_id", "user", "target", "reason", "duration_minutes",
              "start", "end", "status", "commands"]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for s in sessions:
        writer.writerow({**{k: s.get(k, "") for k in fields},
                         "commands": " | ".join(s.get("commands", []))})
    return Response(output.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment;filename=sessions_audit.csv"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
