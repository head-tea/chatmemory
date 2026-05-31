"""
Shared utilities for chatmemory skill.
"""
import re, sys
import logging
from config_loader import (
    WEFLOW_EXE, WEFLOW_API, WEFLOW_TOKEN,
    PROJECT_ROOT, CACHE_DIR, RAW_EXPORT_DIR, CLEANED_DIR, NOTEBOOKLM_DIR,
    EXPORTS_DIR,
)

# ═══ Logging ═════════════════════════════════════════════════════════════════════

LOG_FORMAT = '%(asctime)s [%(levelname)-5s] %(name)s: %(message)s'
LOG_DATE_FMT = '%H:%M:%S'

def setup_logging(name='chatmemory', level=logging.INFO):
    """Configure and return a logger for the given name.

    Writes to stderr so subprocess stdout (link_expander) is clean.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FMT))
        logger.addHandler(h)
    logger.setLevel(level)
    # Don't propagate to root logger (keeps each tool's output separate)
    logger.propagate = False
    return logger

# ═══ Re-exports for backward compatibility ═══════════════════════════════════

TOKEN = WEFLOW_TOKEN
BASE_DIR = str(PROJECT_ROOT)

def safe_filename(name):
    """Convert a contact/group name to a safe filename.

    Handles: reserved names (CON, NUL, PRN, etc.), trailing dots/spaces,
    leading spaces, path separators, and length limits.
    """
    name = name.strip()
    # Replace forbidden characters
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    # Replace control characters
    name = re.sub(r'[\x00-\x1f]', '', name)
    # Collapse whitespace
    name = re.sub(r'\s+', ' ', name)
    # Strip trailing dots and spaces (Windows limitation)
    name = name.rstrip('. ')
    # Handle Windows reserved names (CON, PRN, AUX, NUL, COM1-9, LPT1-9)
    _RESERVED = {'CON', 'PRN', 'AUX', 'NUL',
                 'COM1','COM2','COM3','COM4','COM5','COM6','COM7','COM8','COM9',
                 'LPT1','LPT2','LPT3','LPT4','LPT5','LPT6','LPT7','LPT8','LPT9'}
    base = name.split('.')[0].upper() if '.' in name else name.upper()
    if base in _RESERVED:
        name = '_' + name
    # Truncate with hash to avoid collision
    if len(name) > 80:
        import hashlib
        h = hashlib.md5(name.encode('utf-8')).hexdigest()[:6]
        name = name[:73] + '_' + h
    return name or 'unnamed'

# Ensure all dirs exist
import os
for d in [str(CACHE_DIR), str(RAW_EXPORT_DIR), str(CLEANED_DIR),
          str(NOTEBOOKLM_DIR), str(EXPORTS_DIR)]:
    os.makedirs(d, exist_ok=True)
