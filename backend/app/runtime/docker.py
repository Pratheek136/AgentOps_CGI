"""DockerRuntime: placeholder. See README "Adding Docker" for the plan."""
from __future__ import annotations

from pathlib import Path

from .base import RuntimeStatus, ServiceRuntime, TestRun


class DockerRuntime(ServiceRuntime):
    def __init__(self, name: str, **_: object) -> None:
        self.name = name

    def start(self) -> RuntimeStatus:
        raise NotImplementedError("DockerRuntime is not implemented yet; use RUNTIME=local")

    def stop(self) -> RuntimeStatus:
        raise NotImplementedError("DockerRuntime is not implemented yet; use RUNTIME=local")

    def restart(self) -> RuntimeStatus:
        raise NotImplementedError("DockerRuntime is not implemented yet; use RUNTIME=local")

    def status(self) -> RuntimeStatus:
        raise NotImplementedError("DockerRuntime is not implemented yet; use RUNTIME=local")

    def memory_mb(self) -> float | None:
        raise NotImplementedError("DockerRuntime is not implemented yet; use RUNTIME=local")

    @property
    def logs_path(self) -> Path:
        raise NotImplementedError("DockerRuntime is not implemented yet; use RUNTIME=local")

    def run_tests(self, workdir: Path, timeout_s: float = 90) -> TestRun:
        raise NotImplementedError("DockerRuntime is not implemented yet; use RUNTIME=local")
