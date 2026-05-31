#!/usr/bin/env python3
"""
ChatMemory v1.1 初始化脚本

Usage:
  python setup.py init      创建目录结构 + 生成默认配置
  python setup.py check     检查所有依赖是否就绪
  python setup.py --help    显示帮助
"""

import os
import sys
import json
import shutil
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(r"E:\chatmemory")
REQUIRED_DIRS = [
    "cache",
    "cache/raw_exports",
    "cache/cleaned",
    "cache/notebooklm",
    "exports/wechat",
    "exports/qq",
    "tool",
]

DEFAULT_CONFIG = {
    "_comment": "ChatMemory unified config. Secrets via env vars.",
    "paths": {
        "wechat_data": "",
        "output_base": "E:/chatmemory",
        "cache_dir": "E:/chatmemory/cache",
        "exports_dir": "E:/chatmemory/exports/wechat",
    },
    "weflow": {
        "api_base": "http://127.0.0.1:5031",
        "exe_path": "E:/chatmemory/tool/WeFlow/WeFlow.exe",
        "token": "env:CHATMEMORY_WEFLOW_TOKEN",
    },
    "cleaning": {
        "rules_file": "E:/chatmemory/cleaning_rules.json",
        "fragment_merge": {
            "max_gap_seconds": 120,
            "max_buffer_size": 3,
            "max_content_length": 30,
        },
        "qa_pairing": {
            "max_followups": 5,
            "max_gap_seconds": 600,
            "quick_question_gap_seconds": 60,
        },
        "topic_clustering": {"window_minutes": 30},
        "link_expansion": {
            "enabled": True,
            "github_api": True,
            "wechat_via_urlmd": True,
            "max_concurrent": 3,
            "cache_ttl_hours": 24,
        },
    },
    "output": {"include_audit_samples": True, "max_audit_samples": 20},
}


def cmd_init():
    """Create directory structure and default config."""
    print("ChatMemory v1.1 — Initializing...")
    print()

    # 1. Create directories
    print("[1/5] Creating directories...")
    for d in REQUIRED_DIRS:
        path = PROJECT_ROOT / d
        path.mkdir(parents=True, exist_ok=True)
        print(f"  OK  {d}/")

    # 2. Copy config if not exists
    print("[2/5] Checking config.json...")
    cfg_path = PROJECT_ROOT / "config.json"
    if not cfg_path.exists():
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)
        print(f"  Created {cfg_path}")
    else:
        print(f"  Already exists ({cfg_path})")

    # 3. Copy cleaning_rules.json
    print("[3/5] Copying cleaning_rules.json...")
    rules_src = Path(__file__).parent / "cleaning_rules.json"
    rules_dst = PROJECT_ROOT / "cleaning_rules.json"
    if not rules_dst.exists() and rules_src.exists():
        shutil.copy2(rules_src, rules_dst)
        print(f"  OK  {rules_dst}")
    else:
        print(f"  Skipped (already exists)")

    # 4. Check url-md
    print("[4/5] Checking url-md.exe...")
    urlmd_dst = PROJECT_ROOT / "tool" / "url-md.exe"
    urlmd_src = Path(__file__).parent / "deps" / "url-md.exe"
    if not urlmd_dst.exists() and urlmd_src.exists():
        shutil.copy2(urlmd_src, urlmd_dst)
        print(f"  OK  url-md.exe → tool/")
    elif urlmd_dst.exists():
        print(f"  Already exists ({urlmd_dst})")
    else:
        print(f"  SKIP — url-md.exe not found in deps/")
        print(f"    Download from: https://github.com/url-md/releases")

    # 5. Check WeFlow
    print("[5/5] WeFlow...")
    weflow_exe = PROJECT_ROOT / "tool" / "WeFlow" / "WeFlow.exe"
    weflow_installer = Path(__file__).parent / "deps" / "WeFlow-4.5.1-x64-Setup.exe"
    if weflow_exe.exists():
        print(f"  OK  WeFlow found at {weflow_exe}")
    elif weflow_installer.exists():
        print(f"  Installer found: deps/WeFlow-4.5.1-x64-Setup.exe")
        print(f"    双击安装到: {weflow_exe.parent}")
        print(f"    安装后开启 HTTP API (设置 → HTTP API)")
    else:
        print(f"  NOT FOUND — WeFlow 未安装")
        print(f"    下载: GitHub Releases 页面")
        print(f"    安装到: {weflow_exe.parent}")
        print(f"    安装后开启 HTTP API (设置 → HTTP API)")

    print()
    print("Setup complete!")
    print()
    print("下一步:")
    print("  1. 设置环境变量: set CHATMEMORY_WEFLOW_TOKEN=你的token")
    print("  2. 安装依赖: pip install -r requirements.txt")
    print("  3. 安装 notebooklm CLI: pip install notebooklm-py")
    print("  4. 登录 notebooklm: notebooklm login")
    print("  5. 打开 WeFlow，登录微信")
    print()
    print("然后就可以用了:")
    print('  python scripts/wechat_export.py --all --days 1')


def cmd_check():
    """Check all dependencies."""
    print("ChatMemory v1.1 — Dependency Check")
    print()
    ok = 0
    fail = 0

    checks = [
        ("Python 3.7+", lambda: sys.version_info >= (3, 7)),
        ("Directories exist", lambda: all((PROJECT_ROOT / d).is_dir() for d in REQUIRED_DIRS)),
        ("config.json", lambda: (PROJECT_ROOT / "config.json").is_file()),
        ("cleaning_rules.json", lambda: (PROJECT_ROOT / "cleaning_rules.json").is_file()),
        ("fpdf2 (pip)", lambda: _check_pip("fpdf2")),
        ("notebooklm CLI", lambda: _check_cmd("notebooklm", "--version")),
        ("url-md.exe", lambda: (PROJECT_ROOT / "tool" / "url-md.exe").exists()),
        ("WeFlow.exe", lambda: (PROJECT_ROOT / "tool" / "WeFlow" / "WeFlow.exe").exists()),
        ("CHATMEMORY_WEFLOW_TOKEN", lambda: bool(os.environ.get("CHATMEMORY_WEFLOW_TOKEN"))),
    ]

    for name, check in checks:
        try:
            result = check()
        except Exception:
            result = False
        if result:
            print(f"  [OK]   {name}")
            ok += 1
        else:
            print(f"  [MISS] {name}")
            fail += 1

    print()
    print(f"  {ok} passed, {fail} missing")
    return 0 if fail == 0 else 1


def _check_pip(pkg):
    try:
        subprocess.run(
            [sys.executable, "-c", f"import {pkg}"],
            capture_output=True, timeout=10,
        )
        return True
    except Exception:
        return False


def _check_cmd(cmd, arg=""):
    try:
        result = subprocess.run(
            f"{cmd} {arg}".split(),
            capture_output=True, timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("--help", "-h"):
        print(__doc__)
    elif sys.argv[1] == "init":
        cmd_init()
    elif sys.argv[1] == "check":
        sys.exit(cmd_check())
    else:
        print(f"Unknown command: {sys.argv[1]}")
        print(__doc__)
        sys.exit(1)
