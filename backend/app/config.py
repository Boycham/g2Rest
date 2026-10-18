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


@dataclass(frozen=True)
class Settings:
    token: str = ""
    escalation_sec: float = 30.0
    offline_escalation_sec: float = 120.0
    port: int = 8787
    data_dir: Path = field(default=DATA_DIR)
    cors_origins: tuple[str, ...] = ("*",)

    @classmethod
    def from_env(cls) -> Settings:
        _load_root_env()
        return cls(
            token=os.environ.get("FS_TOKEN", ""),
            escalation_sec=float(os.environ.get("FS_ESCALATION_SEC", "30")),
            offline_escalation_sec=float(os.environ.get("FS_OFFLINE_ESCALATION_SEC", "120")),
            port=int(os.environ.get("FS_PORT", "8787")),
            data_dir=Path(os.environ.get("FS_DATA_DIR", str(DATA_DIR))),
        )
