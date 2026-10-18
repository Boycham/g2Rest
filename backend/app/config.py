"""Settings read from the environment. Keys never live in code."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"


def _load_root_env() -> None:
    """Read the repo-root .env (gitignored) without overriding real env vars."""
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def floor_file(name: str) -> str:
    """`FS_FLOOR`: empty = floor.json (the floor of record), `demo` = floor.demo.json."""
    name = name.strip()
    return f"floor.{name}.json" if name else "floor.json"


@dataclass(frozen=True)
class Settings:
    token: str = ""
    escalation_sec: float = 30.0
    offline_escalation_sec: float = 120.0
    port: int = 8787
    data_dir: Path = field(default=DATA_DIR)
    floor_file: str = "floor.json"  # FS_FLOOR=demo: floor.demo.json (sim/mock_staff.py)
    cors_origins: tuple[str, ...] = ("*",)
    voice_relay_url: str = ""  # empty: no voice bridge, audio frames are only counted
    done_sec: float = 300.0  # accepted but not done this long: alert the manager, reroute
    course_wait_sec: float = 720.0  # a seated table waiting this long on its next course: alert
    vip_alert_sec: float = 300.0  # how long "VIP seated" stays on the manager's list
    gemini_api_key: str = ""  # empty: the router uses the rules only (app/router.py)
    gemini_model: str = "gemini-3.1-flash-lite"
    router_timeout_sec: float = 3.0
    database_url: str = ""  # empty: no Tiger Data copy of the event log (app/eventdb.py)
    sentry_dsn_backend: str = ""  # empty: Sentry off for the backend (app/telemetry.py)
    sentry_dsn_web: str = ""  # empty: GET /config tells the pages Sentry is off
    sentry_environment: str = "dev"
    sentry_traces_rate: float = 1.0
    trace_wire: bool = False  # send `trace` on task.assigned (proposed, CONTRACT.md §8.12)

    @classmethod
    def from_env(cls) -> Settings:
        _load_root_env()
        return cls(
            token=os.environ.get("FS_TOKEN", ""),
            escalation_sec=float(os.environ.get("FS_ESCALATION_SEC", "30")),
            offline_escalation_sec=float(os.environ.get("FS_OFFLINE_ESCALATION_SEC", "120")),
            port=int(os.environ.get("FS_PORT", "8787")),
            data_dir=Path(os.environ.get("FS_DATA_DIR", str(DATA_DIR))),
            floor_file=floor_file(os.environ.get("FS_FLOOR", "")),
            voice_relay_url=os.environ.get("VOICE_RELAY_URL") or "ws://localhost:8790/ws",
            done_sec=float(os.environ.get("FS_DONE_SEC", "300")),
            course_wait_sec=float(os.environ.get("FS_COURSE_WAIT_SEC", "720")),
            vip_alert_sec=float(os.environ.get("FS_VIP_ALERT_SEC", "300")),
            gemini_api_key=os.environ.get("GEMINI_API_KEY", ""),
            gemini_model=os.environ.get("FS_GEMINI_MODEL", "gemini-3.1-flash-lite"),
            router_timeout_sec=float(os.environ.get("FS_ROUTER_TIMEOUT_SEC", "3")),
            database_url=os.environ.get("DATABASE_URL", ""),
            sentry_dsn_backend=os.environ.get("SENTRY_DSN_BACKEND", ""),
            sentry_dsn_web=os.environ.get("SENTRY_DSN_WEB", ""),
            sentry_environment=os.environ.get("SENTRY_ENVIRONMENT", "dev"),
            sentry_traces_rate=float(os.environ.get("FS_SENTRY_TRACES_RATE", "1")),
            trace_wire=os.environ.get("FS_TRACE_WIRE", "") == "1",
        )
