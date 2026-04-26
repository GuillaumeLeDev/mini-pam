#!/bin/sh
set -e
python3 /app/fetch_secret.py
exec /usr/sbin/sshd -D -e
