#!/usr/bin/env python3
"""Bootstrap and run Avtomail locally with a single command."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEV_SCRIPT = ROOT / "scripts" / "dev.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install dependencies, run migrations/tests, and start the server",
    )
    parser.add_argument("--port", type=int, default=8000, help="Port for the API (default: 8000)")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    parser.add_argument("--no-reload", action="store_true", help="Disable uvicorn autoreload")
    parser.add_argument("--run-only", action="store_true", help="Skip installation and run only the server")
    parser.add_argument("--install-only", action="store_true", help="Only install/setup without launching the server")
    return parser.parse_args()


def build_command(args: argparse.Namespace) -> list[str]:
    if not DEV_SCRIPT.exists():
        raise SystemExit("scripts/dev.py not found. Did you clone the repo correctly?")
    cmd: list[str] = [sys.executable, str(DEV_SCRIPT)]
    if args.install_only:
        cmd.append("--install-only")
    if args.run_only:
        cmd.append("--run-only")
    if args.no_reload:
        cmd.append("--no-reload")
    cmd.extend(["--port", str(args.port), "--bind-address", args.host])
    return cmd


def main() -> None:
    args = parse_args()
    command = build_command(args)
    print("Launching:", " ".join(command))
    try:
        subprocess.check_call(command, cwd=str(ROOT))
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc


if __name__ == "__main__":
    main()
