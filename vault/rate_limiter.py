"""Rate limiter — blocks IPs after too many failed auth attempts."""

import time
from collections import defaultdict

WINDOW_SECONDS = 60
MAX_FAILURES = 5

_failures: dict = defaultdict(list)


def record_failure(ip: str):
    now = time.time()
    _failures[ip].append(now)
    _failures[ip] = [t for t in _failures[ip] if now - t < WINDOW_SECONDS]


def is_blocked(ip: str) -> bool:
    now = time.time()
    recent = [t for t in _failures.get(ip, []) if now - t < WINDOW_SECONDS]
    _failures[ip] = recent
    return len(recent) >= MAX_FAILURES
