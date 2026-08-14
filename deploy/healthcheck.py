#!/usr/bin/env python3
"""Healthcheck Nexus : redémarre le service s'il est arrêté ou s'il est
bloqué (heartbeat périmé). À lancer via systemd timer (toutes les 5 min)."""
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

SERVICE = "nexus"
DB = Path("/opt/nexus/data/nexus.db")
STALE_AFTER_SEC = 900  # heartbeat mis à jour toutes les 5 min


def service_active() -> bool:
    return subprocess.run(
        ["systemctl", "is-active", "--quiet", SERVICE]
    ).returncode == 0


def heartbeat_age() -> float | None:
    """Âge du dernier heartbeat en secondes, ou None si absent (jamais vu)."""
    if not DB.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        cur = con.cursor()
        cur.execute("SELECT value FROM kv WHERE key='heartbeat'")
        row = cur.fetchone()
        con.close()
    except Exception:
        return None
    if row is None:
        return None
    try:
        return time.time() - float(row[0])
    except ValueError:
        return None


def restart(reason: str) -> int:
    print(f"HEALTHCHECK: redémarrage de {SERVICE} — {reason}", flush=True)
    subprocess.run(["systemctl", "restart", SERVICE])
    return 1


def main() -> int:
    if not service_active():
        return restart("service inactif")
    age = heartbeat_age()
    if age is not None and age > STALE_AFTER_SEC:
        return restart(f"heartbeat périmé ({age:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
