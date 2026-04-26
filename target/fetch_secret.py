"""Fetch admin password from vault at container startup and apply it."""

import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error

VAULT_URL = os.environ.get("VAULT_URL", "http://vault:5001")
VAULT_API_KEY = os.environ["VAULT_API_KEY"]
SECRET_NAME = os.environ.get("SECRET_NAME", "target-dev-admin")
MAX_RETRIES = 15


def fetch_password() -> str:
    req = urllib.request.Request(
        f"{VAULT_URL}/secrets/{SECRET_NAME}",
        headers={"X-API-Key": VAULT_API_KEY, "X-Owner": "system"},
    )
    resp = urllib.request.urlopen(req, timeout=5)
    return json.loads(resp.read())["value"]


def main():
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            password = fetch_password()
            subprocess.run(
                ["chpasswd"],
                input=f"admin:{password}",
                text=True,
                check=True,
            )
            print(f"[target] Password configured from vault '{SECRET_NAME}' (attempt {attempt})", flush=True)
            return
        except Exception as e:
            print(f"[target] Vault not ready — {e} — retry {attempt}/{MAX_RETRIES}...", flush=True)
            time.sleep(3)

    print("[target] FATAL: could not fetch password from vault after retries", flush=True)
    sys.exit(1)


if __name__ == "__main__":
    main()
