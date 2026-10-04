"""Start the two local projects; model runtime is deliberately independent."""

from pathlib import Path
import json
import os
import signal
import subprocess
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent
children = []


def environment(project):
    env = os.environ.copy()
    path = project / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def health(url):
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
            url, timeout=1
        ) as r:
            return json.load(r)
    except Exception:
        return None


def stop(*_, exit_code=0):
    for child in children:
        if child.poll() is None:
            child.terminate()
    for child in children:
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
    raise SystemExit(exit_code)


signal.signal(signal.SIGINT, stop)
signal.signal(signal.SIGTERM, stop)
try:
    for name, url, args in [
        ("agent-lab", "http://127.0.0.1:8001/health", ["src/main.py"]),
        (
            "business-demo",
            "http://127.0.0.1:8000/api/v1/health",
            ["manage.py", "runserver", "127.0.0.1:8000", "--noreload", "--insecure"],
        ),
    ]:
        project = ROOT / name
        if health(url):
            print(
                f"{name}: already running; this launcher will not stop the existing process.",
                flush=True,
            )
            continue
        python = project / ".venv/bin/python"
        if not python.exists():
            raise RuntimeError(f"{name}: run make setup first.")
        child = subprocess.Popen(
            [str(python), *args], cwd=project, env=environment(project)
        )
        children.append(child)
        for _ in range(40):
            if child.poll() is not None:
                raise RuntimeError(f"{name}: process exited; inspect output above.")
            if health(url):
                break
            time.sleep(0.25)
        else:
            raise RuntimeError(f"{name}: startup timeout.")
    print(
        "Website: http://127.0.0.1:8000 | Ctrl+C stops processes started here.",
        flush=True,
    )
    if os.environ.get("OPEN_BROWSER", "1") == "1":
        webbrowser.open("http://127.0.0.1:8000")
    while children:
        if any(c.poll() is not None for c in children):
            raise RuntimeError("A service stopped unexpectedly.")
        time.sleep(1)
except Exception as error:
    print(error, flush=True)
    stop(exit_code=1)
