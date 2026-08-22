from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


SECRET_ENV_NAMES = [
    "TIKHUB_API_KEY",
    "DINGTALK_WEBHOOK_URL",
    "DINGTALK_WEBHOOK_SECRET",
]


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "detail": self.detail}


def local_doctor(*, no_network: bool = True, root: Path | str = ".") -> list[CheckResult]:
    root_path = Path(root)
    checks: list[CheckResult] = []

    for directory in ["data", "outputs", "logs", "tmp/smoke", "config", "docs", "tasks"]:
        path = root_path / directory
        checks.append(
            CheckResult(
                name=f"dir:{directory}",
                status="ok" if path.exists() and path.is_dir() else "missing",
                detail=str(path),
            )
        )

    for binary in ["codegraph", "agent-reach", "browser-harness"]:
        found = shutil.which(binary)
        checks.append(
            CheckResult(
                name=f"binary:{binary}",
                status="ok" if found else "missing",
                detail=found or "not found on PATH",
            )
        )

    for env_name in SECRET_ENV_NAMES:
        value = os.environ.get(env_name)
        checks.append(
            CheckResult(
                name=f"secret_env:{env_name}",
                status="set" if value else "empty",
                detail="redacted" if value else "empty",
            )
        )

    checks.append(
        CheckResult(
            name="network",
            status="skipped" if no_network else "not_checked",
            detail="no_network=true" if no_network else "network probes are not implemented",
        )
    )
    return checks


def has_blocking_preflight_failure(checks: list[CheckResult]) -> bool:
    return any(check.status == "missing" for check in checks if check.name.startswith(("dir:", "binary:")))

