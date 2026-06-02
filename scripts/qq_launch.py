#!/usr/bin/env python3
"""
QQ Chat Export Launcher — auto-start NapCatQQ (QCE) and wait for OneBot API.

Mirrors wechat_launch.py pattern:
  - Check OneBot HTTP API (:3001) health
  - If not running, launch QCE via launcher-user.bat
  - Poll up to 90 seconds until API ready
"""
import subprocess
import time
import urllib.request
import urllib.error
import os
import sys

from config_loader import QCE_DIR, QCE_QCE_LAUNCHER, ONEBOT_API

ONEBOT_API = ONEBOT_API.rstrip("/")
HEALTH_ENDPOINT = f"{ONEBOT_API}/get_login_info"


def is_api_ready():
    """Check if OneBot HTTP API is responding."""
    try:
        req = urllib.request.Request(
            HEALTH_ENDPOINT,
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def is_qce_running():
    """Check if QCE web UI is already up on port 40653."""
    try:
        urllib.request.urlopen("http://127.0.0.1:40653/health", timeout=3)
        return True
    except Exception:
        return False


def launch():
    """Ensure QCE + OneBot API are running.

    Returns True if API is ready (was already or started successfully).
    """
    if is_api_ready():
        print("[QQ] OneBot API already running on :3001")
        return True

    if not os.path.isfile(QCE_LAUNCHER):
        print(f"[QQ] ERROR: launcher not found: {QCE_LAUNCHER}")
        print(f"[QQ] Download QCE from: https://github.com/shuakami/qq-chat-exporter/releases")
        print(f"[QQ] Extract to: {QCE_DIR}")
        return False

    print(f"[QQ] Starting QCE: {QCE_LAUNCHER} ...")
    try:
        subprocess.Popen(
            [QCE_LAUNCHER],
            shell=True,
            cwd=QCE_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        print(f"[QQ] Cannot launch QCE: {e}")
        return False

    print("[QQ] Waiting for OneBot API...", end="", flush=True)
    for i in range(90):
        time.sleep(1)
        if is_api_ready():
            print(" ready!")
            return True
        print(".", end="", flush=True)
    print(" timeout!")
    return False


if __name__ == "__main__":
    ok = launch()
    sys.exit(0 if ok else 1)
