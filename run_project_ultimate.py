"""One-command launcher for F1 PredictLab.

Usage:
    py run_project.py

Creates a project-local Python environment, installs requirements.txt, finds
Node.js/npm or downloads a portable Node.js LTS ZIP into .tools/node, builds
the frontend, then starts FastAPI on a free local port and opens the browser.
No system-wide Node.js installation or administrator rights are required on Windows.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
FRONTEND = ROOT / "frontend"
REQUIREMENTS = ROOT / "requirements.txt"
TOOLS = ROOT / ".tools"
NODE_HOME = TOOLS / "node"
PORTS = (8000, 8010, 8765, 5050, 7001, 8081, 9090)
NODE_INDEX = "https://nodejs.org/dist/index.json"
HEADERS = {"User-Agent": "F1-PredictLab-Launcher/1.0"}


def say(message: str = "") -> None:
    print(message, flush=True)


def execute(command: list[str], cwd: Path = ROOT, check: bool = True) -> int:
    try:
        result = subprocess.run(command, cwd=str(cwd), check=False)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Executable not found: {command[0]}") from exc
    if check and result.returncode:
        raise RuntimeError(f"Command failed (exit {result.returncode}): {' '.join(command)}")
    return result.returncode


def python_in_venv() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def ensure_python() -> Path:
    python = python_in_venv()
    if not python.exists():
        say("[1/5] Creating project Python environment (.venv)…")
        execute([sys.executable, "-m", "venv", str(VENV)])
    if not REQUIREMENTS.exists():
        raise RuntimeError("requirements.txt is missing from the project root.")
    say("[2/5] Installing/checking Python dependencies…")
    execute([str(python), "-m", "pip", "install", "--upgrade", "pip"])
    execute([str(python), "-m", "pip", "install", "-r", str(REQUIREMENTS)])
    return python


def fetch_json(url: str):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=90) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output)


def node_paths() -> tuple[Path, Path]:
    if os.name == "nt":
        return NODE_HOME / "node.exe", NODE_HOME / "npm.cmd"
    return NODE_HOME / "bin/node", NODE_HOME / "bin/npm"


def install_portable_node() -> tuple[Path, Path]:
    if os.name != "nt":
        raise RuntimeError(
            "Node.js/npm was not found. Automatic portable installation is currently "
            "implemented for Windows; install Node.js LTS for your operating system."
        )
    node, npm = node_paths()
    if node.exists() and (NODE_HOME / "node_modules/npm/bin/npm-cli.js").exists():
        return node, npm

    say("[3/5] Node.js/npm not found. Downloading portable Node.js LTS (no admin install)…")
    try:
        releases = fetch_json(NODE_INDEX)
        release = next((item for item in releases if item.get("lts")), None)
        if not release:
            raise RuntimeError("No Node.js LTS release was found.")
        version = release["version"]
        machine = platform.machine().lower()
        arch = "win-arm64" if machine in ("arm64", "aarch64") else "win-x64"
        archive_name = f"node-{version}-{arch}.zip"
        archive_path = TOOLS / archive_name
        extract_dir = TOOLS / "_node_extract"
        TOOLS.mkdir(parents=True, exist_ok=True)
        download(f"https://nodejs.org/dist/{version}/{archive_name}", archive_path)
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        extract_dir.mkdir(parents=True)
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(extract_dir)
        folders = [item for item in extract_dir.iterdir() if item.is_dir()]
        if not folders:
            raise RuntimeError("Node.js archive did not contain its expected folder.")
        if NODE_HOME.exists():
            shutil.rmtree(NODE_HOME)
        shutil.copytree(folders[0], NODE_HOME)
        archive_path.unlink(missing_ok=True)
        shutil.rmtree(extract_dir, ignore_errors=True)
    except (urllib.error.URLError, TimeoutError, zipfile.BadZipFile, OSError) as exc:
        raise RuntimeError(
            f"Could not download/install portable Node.js: {exc}. "
            "Check your internet connection and try again."
        ) from exc

    node, npm = node_paths()
    if not node.exists() or not (NODE_HOME / "node_modules/npm/bin/npm-cli.js").exists():
        raise RuntimeError("Portable Node.js setup did not finish correctly.")
    say(f"      Node.js installed locally at {NODE_HOME}")
    return node, npm


def get_node() -> tuple[Path, Path]:
    system_node, system_npm = shutil.which("node"), shutil.which("npm")
    if system_node and system_npm:
        return Path(system_node), Path(system_npm)
    return install_portable_node()


def run_npm(node: Path, npm: Path, args: list[str], cwd: Path) -> None:
    # Run npm's JS entry point through node.exe. This avoids Windows cmd.exe
    # quoting failures with paths such as "C:\\Program Files\\nodejs\\npm.CMD".
    possible_cli = [
        npm.parent / "node_modules/npm/bin/npm-cli.js",
        node.parent / "node_modules/npm/bin/npm-cli.js",
    ]
    cli = next((path for path in possible_cli if path.is_file()), None)
    if cli:
        command = [str(node), str(cli), *args]
    elif os.name == "nt":
        command = ["cmd.exe", "/d", "/c", "call", str(npm), *args]
    else:
        command = [str(npm), *args]
    code = execute(command, cwd=cwd, check=False)
    if code:
        raise RuntimeError(f"npm {' '.join(args)} failed with exit code {code}.")


def build_frontend(node: Path, npm: Path) -> None:
    package = FRONTEND / "package.json"
    if not package.is_file():
        say("[4/5] No frontend/package.json found; skipping frontend build.")
        return
    say("[4/5] Installing frontend packages and building the website…")
    if (FRONTEND / "package-lock.json").is_file():
        run_npm(node, npm, ["ci"], FRONTEND)
    else:
        say("      package-lock.json not found; using npm install.")
        run_npm(node, npm, ["install"], FRONTEND)
    run_npm(node, npm, ["run", "build"], FRONTEND)
    if not (FRONTEND / "dist/index.html").is_file():
        say("      Warning: build completed, but frontend/dist/index.html was not found.")
        say("      Check the frontend build output configuration.")


def free_port(preferred: int | None = None) -> int:
    for port in ([preferred] if preferred else []) + list(PORTS):
        if port is None:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def open_when_ready(url: str) -> None:
    for _ in range(120):
        try:
            with urllib.request.urlopen(url + "/health", timeout=1.5) as response:
                if response.status == 200:
                    webbrowser.open(url)
                    return
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(0.5)


def main() -> int:
    parser = argparse.ArgumentParser(description="Start F1 PredictLab with one command.")
    parser.add_argument("--port", type=int, default=None, help="preferred port; uses another free port if busy")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser automatically")
    args = parser.parse_args()

    if not (ROOT / "api/main.py").is_file():
        say("[ERROR] api/main.py was not found. Run this script from the project root.")
        return 2

    try:
        python = ensure_python()
        if Path(sys.prefix).resolve() != VENV.resolve():
            # Relaunch once inside .venv, so imports and uvicorn use installed packages.
            return execute([str(python), str(Path(__file__).resolve()), *sys.argv[1:]], check=False)

        node, npm = get_node()
        build_frontend(node, npm)

        import uvicorn

        port = free_port(args.port)
        url = f"http://127.0.0.1:{port}"
        say("\n[5/5] Starting F1 PredictLab…")
        say(f"      App address: {url}")
        say("      Keep this window open. Press Ctrl+C to stop the app.")
        if not args.no_browser:
            threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
        uvicorn.run("api.main:app", host="127.0.0.1", port=port, log_level="info")
        return 0
    except KeyboardInterrupt:
        say("\nF1 PredictLab stopped.")
        return 0
    except (RuntimeError, OSError, subprocess.SubprocessError, ImportError) as exc:
        say(f"\n[ERROR] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
