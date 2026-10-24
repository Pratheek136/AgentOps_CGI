#!/usr/bin/env python3
"""RootFix demo control. Cross-platform (Windows/macOS/Linux).

  python scripts/demo.py up            start backend (+shop, +traffic) and dashboard
  python scripts/demo.py down          stop everything
  python scripts/demo.py status        show process + service health
  python scripts/demo.py seed          (re)create shop_repo with deploy history
  python scripts/demo.py reset         back to last good deploy, clear incidents
  python scripts/demo.py fault <n>     inject scenario n (1-6) as a bad deploy
  python scripts/demo.py record <s>    run with RECORD_REPLAYS=true for scenario s
  python scripts/demo.py replay <s>    run with LLM_PROVIDER=replay for scenario s
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"
IS_WIN = sys.platform == "win32"
VENV_PY = VENV / ("Scripts/python.exe" if IS_WIN else "bin/python")
PIDS = ROOT / "data" / "pids.json"
LOGS = ROOT / "logs"


# ---------------------------------------------------------------- bootstrap
def _in_venv() -> bool:
    return Path(sys.prefix).resolve() == VENV.resolve()


def ensure_venv() -> None:
    """Create .venv + install requirements if needed, then re-run inside it."""
    if _in_venv():
        return
    if not VENV_PY.exists():
        print("Creating .venv …")
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV)])
        subprocess.check_call([str(VENV_PY), "-m", "pip", "install", "-q", "-r",
                               str(ROOT / "backend" / "requirements.txt")])
    sys.exit(subprocess.call([str(VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]]))


def env() -> dict[str, str]:
    path = ROOT / ".env"
    if not path.exists():
        shutil.copy(ROOT / ".env.example", path)
        print("Created .env from .env.example (add API keys there).")
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def port(name: str, default: int) -> int:
    try:
        return int(env().get(name, default))
    except ValueError:
        return default


def backend_url() -> str:
    return f"http://127.0.0.1:{port('BACKEND_PORT', 8000)}"


# ---------------------------------------------------------------- http
def http(method: str, path: str, body: dict | None = None, timeout: float = 60) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(backend_url() + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def wait_http(url: str, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status < 500:
                    return True
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            pass
        time.sleep(0.5)
    return False


def backend_up() -> bool:
    return wait_http(backend_url() + "/api/health", 1)


# ---------------------------------------------------------------- processes
def spawn(name: str, cmd: list[str], cwd: Path, extra_env: dict[str, str] | None = None) -> int:
    LOGS.mkdir(exist_ok=True)
    log = open(LOGS / f"{name}.log", "ab")
    kwargs: dict = {}
    if IS_WIN:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    p = subprocess.Popen(cmd, cwd=cwd, stdout=log, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, env={**os.environ, **(extra_env or {})}, **kwargs)
    return p.pid


def kill_tree(pid: int, grace: float = 8) -> None:
    import psutil
    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    children = parent.children(recursive=True)
    try:
        parent.terminate()  # lets uvicorn run its shutdown (stops shop + traffic)
    except psutil.Error:
        pass
    _, alive = psutil.wait_procs([parent], timeout=grace)
    rest = [c for c in children if c.is_running()] + alive
    for p in rest:
        try:
            p.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(rest, timeout=3)
    for p in alive:
        try:
            p.kill()
        except psutil.Error:
            pass


def port_free(p: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", p)) != 0


# ---------------------------------------------------------------- commands
def cmd_up(extra_env: dict[str, str] | None = None) -> None:
    e = env()
    if PIDS.exists() and backend_up():
        print("Already running. Use `python scripts/demo.py down` first.")
        return
    bport, dport, sport = port("BACKEND_PORT", 8000), port("DASHBOARD_PORT", 5173), port("SHOP_PORT", 5000)
    busy = [p for p in (bport, dport, sport) if not port_free(p)]
    if busy:
        print(f"Port(s) in use: {busy}. Stop whatever uses them (macOS: AirPlay Receiver uses 5000; "
              f"set SHOP_PORT=5050 in .env) or run `python scripts/demo.py down`.")
        sys.exit(1)
    if not (ROOT / "shop_repo").exists():
        cmd_seed()
    dash = ROOT / "dashboard"
    npm = "npm.cmd" if IS_WIN else "npm"
    if not (dash / "node_modules").exists():
        print("Installing dashboard dependencies …")
        subprocess.check_call([npm, "install", "--no-audit", "--no-fund"], cwd=dash)

    print("Starting backend (it supervises the shop and traffic) …")
    pids = {"backend": spawn("backend", [str(VENV_PY), "-m", "uvicorn", "app.main:app",
                                         "--host", "127.0.0.1", "--port", str(bport)],
                             ROOT / "backend", extra_env)}
    print("Starting dashboard dev server …")
    pids["dashboard"] = spawn("dashboard", [npm, "run", "dev", "--", "--host", "127.0.0.1"], dash,
                              {"BACKEND_PORT": str(bport), "DASHBOARD_PORT": str(dport)})
    PIDS.parent.mkdir(exist_ok=True)
    PIDS.write_text(json.dumps(pids))

    ok_b = wait_http(backend_url() + "/api/health", 45)
    ok_d = wait_http(f"http://127.0.0.1:{dport}/", 45)
    if not (ok_b and ok_d):
        print(f"Startup problem (backend={ok_b}, dashboard={ok_d}). See logs/backend.log, logs/dashboard.log")
        sys.exit(1)
    print(f"\nRootFix is up.\n  Dashboard: http://localhost:{dport}\n  Backend:   {backend_url()}"
          f"\n  Shop:      http://127.0.0.1:{sport}\n  Provider:  {(extra_env or {}).get('ROOTFIX_LLM_PROVIDER') or e.get('LLM_PROVIDER', 'replay')}"
          f"{'  (recording replays)' if (extra_env or {}).get('ROOTFIX_RECORD_REPLAYS') else ''}"
          f"\nStop with: python scripts/demo.py down")


def cmd_down() -> None:
    if not PIDS.exists():
        print("Nothing recorded as running.")
        return
    pids = json.loads(PIDS.read_text())
    for name in ("dashboard", "backend"):
        if name in pids:
            print(f"Stopping {name} (pid {pids[name]}) …")
            kill_tree(pids[name])
    PIDS.unlink(missing_ok=True)
    print("Stopped.")


def cmd_status() -> None:
    if not backend_up():
        print("Backend not reachable. Start with `python scripts/demo.py up`.")
        return
    print(json.dumps(http("GET", "/api/health"), indent=2))


def cmd_seed() -> None:
    sys.path.insert(0, str(ROOT / "backend"))
    from app.seed import seed_repo  # noqa: E402
    seed_repo()


def cmd_reset() -> None:
    if not backend_up():
        print("Backend not running; re-seeding shop_repo offline.")
        cmd_seed()
        return
    t0 = time.time()
    print(json.dumps(http("POST", "/api/demo/reset"), indent=2))
    print(f"Reset in {time.time() - t0:.1f}s")


def cmd_fault(n: str) -> None:
    if not backend_up():
        print("Backend not running. Start with `python scripts/demo.py up`.")
        sys.exit(1)
    print(json.dumps(http("POST", f"/api/demo/fault/{n}"), indent=2))


def cmd_record(scenario: str) -> None:
    cmd_down()
    cmd_up({"ROOTFIX_RECORD_REPLAYS": "true"})
    print(f"Recording replays: now run `python scripts/demo.py fault {scenario}` (saved to fixtures/replays/scenario{scenario}/)")


def cmd_replay(scenario: str) -> None:
    cmd_down()
    cmd_up({"ROOTFIX_LLM_PROVIDER": "replay", "ROOTFIX_REPLAY_SCENARIO": f"scenario{scenario}"})


def main() -> None:
    ensure_venv()
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    c, rest = args[0], args[1:]
    table = {
        "up": lambda: cmd_up(), "down": cmd_down, "status": cmd_status, "seed": cmd_seed,
        "reset": cmd_reset,
        "fault": lambda: cmd_fault(rest[0]) if rest else print("usage: fault <1-6>"),
        "record": lambda: cmd_record(rest[0]) if rest else print("usage: record <1-5>"),
        "replay": lambda: cmd_replay(rest[0]) if rest else print("usage: replay <1-5>"),
    }
    if c not in table:
        print(__doc__)
        sys.exit(2)
    table[c]()


if __name__ == "__main__":
    main()
