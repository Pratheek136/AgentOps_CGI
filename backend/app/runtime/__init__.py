"""Runtime selection. `RUNTIME=local` (default) or `docker` (stub)."""
from __future__ import annotations

import sys
from functools import lru_cache

from ..config import paths, settings
from .base import RuntimeStatus, ServiceRuntime, TestRun
from .docker import DockerRuntime
from .local import LocalProcessRuntime

__all__ = ["RuntimeStatus", "ServiceRuntime", "TestRun", "get_shop_runtime", "get_traffic_runtime"]


def _python() -> str:
    return sys.executable


@lru_cache(maxsize=1)
def get_shop_runtime() -> ServiceRuntime:
    if settings.runtime == "docker":
        return DockerRuntime("shop")
    return LocalProcessRuntime(
        name="shop",
        cmd=[_python(), "serve.py"],
        cwd=paths.shop_repo,
        logs_path=paths.logs / "shop.log",
        health_url=f"{settings.shop_url}/health",
        env={
            "SHOP_PORT": str(settings.shop_port),
            "SHOP_LOG_PATH": str(paths.logs / "shop.log"),
            "PAYMENT_OUTAGE_FLAG": str(paths.data / "payment_outage.flag"),
        },
    )


@lru_cache(maxsize=1)
def get_traffic_runtime() -> ServiceRuntime:
    if settings.runtime == "docker":
        return DockerRuntime("traffic")
    return LocalProcessRuntime(
        name="traffic",
        cmd=[_python(), str(paths.traffic)],
        cwd=paths.root,
        logs_path=paths.logs / "traffic.log",
        env={
            "SHOP_URL": settings.shop_url,
            "TRAFFIC_RPS": str(settings.traffic_rps),
            "ROOTFIX_DB": str(paths.db),
        },
    )
