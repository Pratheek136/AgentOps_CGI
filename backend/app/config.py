"""Environment, paths, thresholds, SLA table and demo users."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def _env(name: str, default: str) -> str:
    raw = os.getenv(name, default)
    # allow inline comments in .env ("VALUE   # comment")
    return raw.split(" #")[0].strip() if raw else default


def _int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    return _env(name, "true" if default else "false").lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Paths:
    root: Path = ROOT
    shop_repo: Path = ROOT / "shop_repo"
    shop_template: Path = ROOT / "shop"
    logs: Path = ROOT / "logs"
    data: Path = ROOT / "data"
    db: Path = ROOT / "data" / "rootfix.db"
    kb: Path = ROOT / "backend" / "app" / "kb"
    replays: Path = ROOT / "fixtures" / "replays"
    traffic: Path = ROOT / "traffic" / "generator.py"


@dataclass(frozen=True)
class Settings:
    runtime: str = _env("RUNTIME", "local")
    shop_port: int = _int("SHOP_PORT", 5000)
    backend_port: int = _int("BACKEND_PORT", 8000)
    dashboard_port: int = _int("DASHBOARD_PORT", 5173)

    llm_provider: str = _env("LLM_PROVIDER", "replay")
    gemini_model: str = _env("GEMINI_MODEL", "")
    grok_model: str = _env("GROK_MODEL", "")
    record_replays: bool = _bool("RECORD_REPLAYS", False)
    replay_scenario: str = _env("REPLAY_SCENARIO", "scenario1")

    demo_mode: bool = _bool("DEMO_MODE", True)
    verify_window_s: int = _int("VERIFY_WINDOW_S", 60)
    approval_timeout_s: int = _int("APPROVAL_TIMEOUT_S", 600)
    max_steps: int = _int("MAX_STEPS", 15)
    max_gated_actions: int = _int("MAX_GATED_ACTIONS", 3)
    max_patches: int = _int("MAX_PATCHES", 2)
    agent_budget_s: int = _int("AGENT_BUDGET_S", 600)
    traffic_rps: float = float(_int("TRAFFIC_RPS", 3))
    auto_close_s: int = _int("AUTO_CLOSE_S", 120)
    slack_webhook_url: str = _env("SLACK_WEBHOOK_URL", "")

    @property
    def shop_url(self) -> str:
        return f"http://127.0.0.1:{self.shop_port}"

    @property
    def effective_verify_window_s(self) -> int:
        return 30 if self.demo_mode else self.verify_window_s


@dataclass(frozen=True)
class Thresholds:
    poll_interval_s: float = 2.0
    error_rate: float = 0.05          # checkout error rate
    error_rate_for_s: int = 20
    p95_ms: float = 1500.0
    p95_for_s: int = 30
    memory_mb_abs: float = 400.0      # no container limit locally: absolute RSS ceiling
    memory_rising_for_s: int = 60
    memory_slope_mb_per_min: float = 8.0
    health_failures: int = 3
    recovered_error_rate: float = 0.01


# priority -> (respond minutes, resolve minutes)
SLA_TABLE: dict[str, tuple[int, int]] = {
    "P1": (5, 30),
    "P2": (15, 120),
    "P3": (60, 480),
    "P4": (240, 4320),
}

REVENUE_ENDPOINTS = {"/checkout", "/cart", "payment"}


@dataclass(frozen=True)
class User:
    name: str
    role: str  # on-call-lead | on-call-engineer | viewer

    @property
    def can_approve(self) -> bool:
        return self.role != "viewer"


USERS: list[User] = [
    User("Pratheek Shenoy", "on-call-lead"),
    User("Samarth Veeraraje Urs", "on-call-engineer"),
    User("Viewer", "viewer"),
]
ON_CALL_ROLES = {"on-call-lead", "on-call-engineer"}


def find_user(name: str) -> User | None:
    return next((u for u in USERS if u.name == name), None)


paths = Paths()
settings = Settings()
thresholds = Thresholds()


def llm_config() -> dict:
    """Fresh read of LLM settings from .env (so keys can be added without a restart).

    `demo.py record|replay` force values via ROOTFIX_* process variables.
    """
    from dotenv import dotenv_values

    file = {k: (v or "").split(" #")[0].strip() for k, v in dotenv_values(ROOT / ".env").items()}

    def get(key: str, default: str = "") -> str:
        return os.getenv(f"ROOTFIX_{key}") or file.get(key) or os.getenv(key) or default

    for k in ("GEMINI_API_KEY", "XAI_API_KEY"):
        if file.get(k):
            os.environ[k] = file[k]
    return {
        "provider": get("LLM_PROVIDER", "replay").lower(),
        "gemini_model": get("GEMINI_MODEL"),
        "grok_model": get("GROK_MODEL"),
        "record": get("RECORD_REPLAYS", "false").lower() in {"1", "true", "yes", "on"},
        "scenario": os.getenv("ROOTFIX_REPLAY_SCENARIO", ""),  # else: the injected scenario
        # on-call policy "mitigate first": for memory incidents restart, verify, then fix the root cause
        "memory_restart_first": get("MEMORY_RESTART_FIRST", "true").lower() in {"1", "true", "yes", "on"},
    }
