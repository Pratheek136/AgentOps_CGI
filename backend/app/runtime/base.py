"""ServiceRuntime: the only way RootFix starts, stops or inspects a service.

Tools, the monitor and demo controls talk to this interface, never to
subprocess or Docker directly, so a DockerRuntime can be dropped in later.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RuntimeStatus:
    name: str
    running: bool
    healthy: bool
    pid: int | None = None
    uptime_s: float | None = None
    detail: str = ""


class ServiceRuntime(ABC):
    name: str

    @abstractmethod
    def start(self) -> RuntimeStatus: ...

    @abstractmethod
    def stop(self) -> RuntimeStatus: ...

    @abstractmethod
    def restart(self) -> RuntimeStatus: ...

    @abstractmethod
    def status(self) -> RuntimeStatus: ...

    @abstractmethod
    def memory_mb(self) -> float | None: ...

    @property
    @abstractmethod
    def logs_path(self) -> Path: ...

    @abstractmethod
    def run_tests(self, workdir: Path, timeout_s: float = 90) -> "TestRun":
        """Run the service's test suite against a checkout (e.g. a git worktree)."""


@dataclass
class TestRun:
    passed: bool
    summary: str
    output: str
    duration_s: float
