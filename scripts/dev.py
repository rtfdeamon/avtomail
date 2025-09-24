#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Dict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
VENV_DIR = PROJECT_ROOT / ".venv"
LOG_DIR = PROJECT_ROOT / "logs"
ENV_FILE = PROJECT_ROOT / ".env"
ENV_EXAMPLE = PROJECT_ROOT / ".env.example"


class CommandError(RuntimeError):
    pass


def ensure_python_version() -> None:
    if sys.version_info < (3, 11):
        raise SystemExit("Python 3.11 or newer is required to run this project.")


def venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def run(cmd: list[str | Path], *, cwd: Path | None = None, env: Dict[str, str] | None = None) -> None:
    process = subprocess.run([str(part) for part in cmd], cwd=cwd, env=env)
    if process.returncode != 0:
        raise CommandError(f"Command failed with exit code {process.returncode}: {' '.join(map(str, cmd))}")


def ensure_venv() -> None:
    if VENV_DIR.exists():
        return
    print("Creating virtual environment in .venv")
    run([Path(sys.executable), "-m", "venv", VENV_DIR])


def install_dependencies() -> None:
    python = venv_python()
    print("Upgrading packaging tooling")
    run([python, "-m", "pip", "install", "--upgrade", "pip", "wheel", "setuptools"])
    print("Installing project dependencies")
    run([python, "-m", "pip", "install", "-e", ".[dev]"])


def ensure_env_file() -> None:
    if ENV_FILE.exists() or not ENV_EXAMPLE.exists():
        return
    print("Creating .env from .env.example")
    shutil.copyfile(ENV_EXAMPLE, ENV_FILE)


def parse_dotenv(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        values[key] = value
    return values


def build_env(dotenv_values: Dict[str, str]) -> Dict[str, str]:
    env = os.environ.copy()
    env.update(dotenv_values)
    current_pythonpath = env.get("PYTHONPATH")
    pythonpath_parts = [str(BACKEND_DIR)]
    if current_pythonpath:
        pythonpath_parts.append(current_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
    return env


def ensure_log_dir() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def run_tests(env: Dict[str, str]) -> str:
    python = venv_python()
    print('Running test suite (pytest)')
    result = subprocess.run([python, '-m', 'pytest', '--maxfail=1', '--disable-warnings', '-q'], cwd=PROJECT_ROOT, env=env)
    if result.returncode == 0:
        summary = 'pytest OK'
        print('Autotests passed: pytest')
    else:
        summary = 'pytest FAILED'
        print('Autotests failed: pytest')
    return summary


def run_migrations(env: Dict[str, str]) -> None:
    python = venv_python()
    print("Running database migrations")
    run([python, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"], cwd=BACKEND_DIR, env=env)


def find_available_port(host: str, preferred_port: int, *, attempts: int = 20) -> tuple[int, OSError | None]:
    port = preferred_port
    last_error: OSError | None = None
    for _ in range(attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
            except OSError as exc:  # port is not available
                last_error = exc
                port += 1
                continue
        return port, last_error if port != preferred_port else None
    raise SystemExit(f"Could not find a free port starting from {preferred_port} (last error: {last_error})")



def start_uvicorn(env: Dict[str, str], *, bind_address: str, port: int, reload: bool) -> None:
    python = venv_python()
    args: list[str | Path] = [python, "-m", "uvicorn", "app.main:app", "--host", bind_address, "--port", str(port)]
    if reload:
        args.append("--reload")
    run(args, cwd=BACKEND_DIR, env=env)


def main() -> None:
    ensure_python_version()

    parser = argparse.ArgumentParser(description='Bootstrap and run the Avtomail backend')
    parser.add_argument('--install-only', action='store_true', help='Only install dependencies and run migrations')
    parser.add_argument('--run-only', action='store_true', help='Skip dependency installation and run only the server')
    parser.add_argument('--no-reload', action='store_true', help='Disable uvicorn autoreload')
    parser.add_argument('--port', type=int, default=8000, help='Port for uvicorn (default: 8000)')
    parser.add_argument('--bind-address', default='127.0.0.1', help='Address to bind uvicorn (default: 127.0.0.1)')
    args = parser.parse_args()

    if args.install_only and args.run_only:
        parser.error('Use either --install-only or --run-only, not both')

    needs_install = not args.run_only
    needs_run = not args.install_only

    if needs_install:
        ensure_venv()
        ensure_env_file()
    else:
        if not VENV_DIR.exists():
            raise SystemExit('Virtual environment not found. Run without --run-only to set it up first.')
        ensure_env_file()

    dotenv_values = parse_dotenv(ENV_FILE)
    env = build_env(dotenv_values)

    ensure_log_dir()

    if needs_install:
        install_dependencies()
        run_migrations(env)
        if args.install_only:
            print('Dependencies installed and migrations applied. Run again without --install-only to start the server.')
            return

    if not needs_run:
        return

    test_summary = run_tests(env)

    final_port, port_error = find_available_port(args.bind_address, args.port)
    if port_error is not None:
        reason = port_error.strerror or str(port_error)
        print(f"Port {args.port} unavailable ({reason}). Switching to {final_port}.")

    print(f"Autotests: {test_summary}")
    print(f"Starting API at http://{args.bind_address}:{final_port}")
    start_uvicorn(env, bind_address=args.bind_address, port=final_port, reload=not args.no_reload)



if __name__ == "__main__":
    try:
        main()
    except CommandError as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        sys.exit(130)
