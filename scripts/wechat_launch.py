#!/usr/bin/env python3
"""
Auto-start WeFlow if not already running.
"""
import sys, os, time, subprocess, urllib.request, urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import WEFLOW_EXE, WEFLOW_API

HEALTH_URL = f"{WEFLOW_API}/health"

def is_running():
    try:
        urllib.request.urlopen(HEALTH_URL, timeout=3)
        return True
    except Exception:
        return False

def launch():
    """Start WeFlow and wait for API readiness."""
    print("[launch] WeFlow not running, starting...")
    try:
        subprocess.Popen(
            [WEFLOW_EXE],
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        print(f"[launch] ERROR starting WeFlow: {e}")
        return False

    print("[launch] Waiting for API...", end='', flush=True)
    for i in range(60):
        time.sleep(1)
        if is_running():
            print(" OK")
            return True
        print('.', end='', flush=True)

    print(" TIMEOUT")
    return False

if __name__ == '__main__':
    if is_running():
        print("[launch] WeFlow API already running")
    else:
        ok = launch()
        if not ok:
            print("[launch] ERROR: Could not start WeFlow. Is it installed at E:\\chatmemory\\tool\\WeFlow\\?")
            sys.exit(1)

    print(f"[launch] WeFlow API ready at {WEFLOW_API}")
