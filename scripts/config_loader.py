r"""
Single source of truth for all ChatMemory configuration.

Loads E:\chatmemory\config.json once at import time.
All scripts import from here instead of hardcoding paths/tokens/TTLs.
"""

import json
import os
from pathlib import Path

_CONFIG_PATH = Path(r"E:\chatmemory\config.json")

def _load() -> dict:
    if not _CONFIG_PATH.is_file():
        raise FileNotFoundError(f"Config not found: {_CONFIG_PATH}")
    with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)

def _resolve_env(value: str) -> str:
    """Resolve 'env:VAR_NAME' references to environment variables."""
    if isinstance(value, str) and value.startswith("env:"):
        var = value[4:]
        val = os.environ.get(var)
        if not val:
            raise RuntimeError(
                f"Environment variable {var} is not set "
                f"(required by {_CONFIG_PATH})."
            )
        return val
    return value

_cfg = _load()

# ═══ Paths ═══════════════════════════════════════════════════════════════════

PROJECT_ROOT    = Path(_cfg["paths"]["output_base"])
CACHE_DIR       = Path(_cfg["paths"]["cache_dir"])
EXPORTS_DIR     = Path(_cfg["paths"]["exports_dir"])
RAW_EXPORT_DIR  = CACHE_DIR / "raw_exports"
CLEANED_DIR     = CACHE_DIR / "cleaned"
NOTEBOOKLM_DIR  = CACHE_DIR / "notebooklm"

# ═══ WeFlow ══════════════════════════════════════════════════════════════════

WEFLOW_EXE      = _cfg["weflow"]["exe_path"]
WEFLOW_API      = _cfg["weflow"]["api_base"]
WEFLOW_TOKEN    = _resolve_env(_cfg["weflow"]["token"])

# ═══ OneBot (QQ via NapCatQQ) ═══════════════════════════════════════════════

ONEBOT_API      = _cfg["onebot"]["api_base"]
QCE_DIR         = _cfg["onebot"]["qce_dir"]
QCE_LAUNCHER    = _cfg["onebot"]["launcher"]

# ═══ Decrypt ═════════════════════════════════════════════════════════════════

DECRYPT_TOOL_DIR = Path(_cfg["decrypt"]["tool_dir"])

# ═══ Cleaning ════════════════════════════════════════════════════════════════

CLEANING_RULES_FILE = Path(_cfg["cleaning"]["rules_file"])

FRAG_MAX_GAP    = _cfg["cleaning"]["fragment_merge"]["max_gap_seconds"]
FRAG_MAX_BUF    = _cfg["cleaning"]["fragment_merge"]["max_buffer_size"]
FRAG_MAX_LEN    = _cfg["cleaning"]["fragment_merge"]["max_content_length"]

QA_MAX_FUP      = _cfg["cleaning"]["qa_pairing"]["max_followups"]
QA_MAX_GAP      = _cfg["cleaning"]["qa_pairing"]["max_gap_seconds"]
QA_QUICK_GAP    = _cfg["cleaning"]["qa_pairing"]["quick_question_gap_seconds"]

TOPIC_WINDOW    = _cfg["cleaning"]["topic_clustering"]["window_minutes"]

LINK_EXPANSION_ENABLED = _cfg["cleaning"]["link_expansion"]["enabled"]
LINK_GITHUB_API = _cfg["cleaning"]["link_expansion"]["github_api"]
LINK_WECHAT_URLMD = _cfg["cleaning"]["link_expansion"]["wechat_via_urlmd"]
LINK_MAX_CONCURRENT = _cfg["cleaning"]["link_expansion"]["max_concurrent"]
LINK_CACHE_TTL  = _cfg["cleaning"]["link_expansion"]["cache_ttl_hours"]

# ═══ Output ══════════════════════════════════════════════════════════════════

AUDIT_MAX       = _cfg["output"]["max_audit_samples"]

# ═══ Extra: url-md path ═════════════════════════════════════════════════════

URL_MD_PATHS = [
    str(PROJECT_ROOT / "tool" / "url-md.exe"),
    os.path.expanduser("~/.url-md/bin/url-md"),
]
