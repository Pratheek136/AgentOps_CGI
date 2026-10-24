"""LocalProcessRuntime: runs a service as a supervised local subprocess."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import psutil

from .base import RuntimeStatus, ServiceRuntime, TestRun

log = logging.getLogger("rootfix.runtime")


class LocalProcessRuntime(ServiceRuntime):
    def __init__(
        self,
        name: str,
        cmd: list[str],
        cwd: Path,
        logs_path: Path,
        health_url: str | None = None,
        env: dict[str, str] | None = None,
        start_timeout_s: float = 15.0,
    ) -> None:
        self.name = name
        self._cmd = cmd
        self._cwd = cwd
        self._logs_path = logs_path
        self._health_url = health_url
        self._env = env or {}
        self._start_timeout_s = start_timeout_s
        self._proc: subprocess.Popen | None = None
        self._started_at: float | None = None
        self._lock = threading.RLock()

    @property
    def logs_path(self) -> Path:
        return self._logs_path

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> RuntimeStatus:
        with self._lock:
            if self._alive():
                return self.status()
            self._logs_path.parent.mkdir(parents=True, exist_ok=True)
            stdout_path = self._logs_path.with_suffix(".stdout.log")
            out = open(stdout_path, "ab")
            env = {**os.environ, **self._env, "PYTHONUNBUFFERED": "1"}
            kwargs: dict = {}
            if sys.platform == "win32":
                kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            log.info("starting %s: %s (cwd=%s)", self.name, " ".join(self._cmd), self._cwd)
            self._proc = subprocess.Popen(
                self._cmd, cwd=self._cwd, env=env, stdout=out, stderr=subprocess.STDOUT, **kwargs
            )
            out.close()
            self._started_at = time.time()
            self._wait_healthy()
            return self.status()

    def stop(self) -> RuntimeStatus:
        with self._lock:
            if self._proc is not None:
                log.info("stopping %s (pid %s)", self.name, self._proc.pid)
                _kill_tree(self._proc.pid)
                try:
                    self._proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
            self._proc = None
            self._started_at = None
            return self.status()

    def restart(self) -> RuntimeStatus:
        with self._lock:
            self.stop()
            return self.start()

    # -- inspection --------------------------------------------------------
    def status(self) -> RuntimeStatus:
        running = self._alive()
        healthy = running and self._check_health()
        return RuntimeStatus(
            name=self.name,
            running=running,
            healthy=healthy,
            pid=self._proc.pid if running and self._proc else None,
            uptime_s=round(time.time() - self._started_at, 1) if running and self._started_at else None,
        )

    def memory_mb(self) -> float | None:
        if not self._alive() or self._proc is None:
            return None
        try:
            p = psutil.Process(self._proc.pid)
            rss = p.memory_info().rss + sum(c.memory_info().rss for c in p.children(recursive=True))
            return round(rss / (1024 * 1024), 1)
        except psutil.Error:
            return None

    def run_tests(self, workdir: Path, timeout_s: float = 90) -> TestRun:
        """Fixed argv (no shell): python -m pytest -q in the given checkout."""
        t0 = time.time()
        cmd = [sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider", "tests"]
        try:
            proc = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True, timeout=timeout_s,
                                  env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            out = (proc.stdout + proc.stderr)[-6000:]
            lines = [l for l in out.strip().splitlines() if l.strip()]
            return TestRun(proc.returncode == 0, lines[-1] if lines else "no output", out,
                           round(time.time() - t0, 1))
        except subprocess.TimeoutExpired:
            return TestRun(False, f"timed out after {timeout_s}s", "", round(time.time() - t0, 1))

    # -- helpers -----------------------------------------------------------
    def _alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _check_health(self) -> bool:
        if not self._health_url:
            return True
        try:
            return httpx.get(self._health_url, timeout=1.0).status_code == 200
        except httpx.HTTPError:
            return False

    def _wait_healthy(self) -> None:
        if not self._health_url:
            return
        deadline = time.time() + self._start_timeout_s
        while time.time() < deadline:
            if not self._alive():
                log.error("%s exited during startup; see %s", self.name, self._logs_path)
                return
            if self._check_health():
                return
            time.sleep(0.2)
        log.warning("%s did not become healthy within %ss", self.name, self._start_timeout_s)


def _kill_tree(pid: int) -> None:
    try:
        parent = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    procs = parent.children(recursive=True) + [parent]
    for p in procs:
        try:
            p.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(procs, timeout=4)
    for p in alive:
        try:
            p.kill()
        except psutil.Error:
            pass
