from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_PROFILE_DIR = Path.home() / ".reddit-voc" / "chrome-profile"
DEFAULT_START_URL = "https://www.reddit.com/login/"
DEFAULT_REMOTE_DEBUG_PORT = 9333


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def normalize_profile_dir(profile_dir: Path | str | None = None) -> Path:
    if profile_dir is None:
        return DEFAULT_PROFILE_DIR.resolve()
    return Path(profile_dir).expanduser().resolve()


def profile_inside_workspace(profile_dir: Path, workspace_root: Path | str = ".") -> bool:
    root = Path(workspace_root).expanduser().resolve()
    return _is_relative_to(profile_dir, root)


@dataclass(frozen=True)
class BrowserProfileStatus:
    profile_dir: str
    exists: bool
    inside_workspace: bool
    has_default_preferences: bool
    has_cookie_store: bool
    login_state: str
    provider_call: bool = False
    live_send: bool = False
    reddit_write: bool = False
    secrets_written: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "profile_dir": self.profile_dir,
            "exists": self.exists,
            "inside_workspace": self.inside_workspace,
            "has_default_preferences": self.has_default_preferences,
            "has_cookie_store": self.has_cookie_store,
            "login_state": self.login_state,
            "provider_call": self.provider_call,
            "live_send": self.live_send,
            "reddit_write": self.reddit_write,
            "secrets_written": self.secrets_written,
        }


def inspect_browser_profile(
    profile_dir: Path | str | None = None,
    *,
    workspace_root: Path | str = ".",
) -> BrowserProfileStatus:
    path = normalize_profile_dir(profile_dir)
    inside_workspace = profile_inside_workspace(path, workspace_root)
    exists = path.exists() and path.is_dir()
    has_default_preferences = (path / "Default" / "Preferences").exists()
    has_cookie_store = (path / "Default" / "Cookies").exists() or (path / "Default" / "Network" / "Cookies").exists()
    if inside_workspace:
        login_state = "blocked_profile_inside_workspace"
    elif not exists:
        login_state = "profile_missing"
    elif has_cookie_store:
        login_state = "profile_present_login_unverified"
    else:
        login_state = "manual_login_required"
    return BrowserProfileStatus(
        profile_dir=str(path),
        exists=exists,
        inside_workspace=inside_workspace,
        has_default_preferences=has_default_preferences,
        has_cookie_store=has_cookie_store,
        login_state=login_state,
    )


def init_browser_profile(
    profile_dir: Path | str | None = None,
    *,
    workspace_root: Path | str = ".",
) -> dict[str, Any]:
    path = normalize_profile_dir(profile_dir)
    if profile_inside_workspace(path, workspace_root):
        status = inspect_browser_profile(path, workspace_root=workspace_root).as_dict()
        return {
            "status": "blocked",
            "reason": "profile_inside_workspace",
            **status,
        }
    path.mkdir(parents=True, exist_ok=True)
    status = inspect_browser_profile(path, workspace_root=workspace_root).as_dict()
    return {
        "status": "ready_for_manual_login" if status["login_state"] == "manual_login_required" else "ok",
        **status,
    }


def build_chrome_launch_command(
    profile_dir: Path | str | None = None,
    *,
    start_url: str = DEFAULT_START_URL,
    app_name: str = "Google Chrome",
    remote_debug_port: int | None = None,
) -> list[str]:
    path = normalize_profile_dir(profile_dir)
    command = [
        "open",
        "-na",
        app_name,
        "--args",
        f"--user-data-dir={path}",
        "--profile-directory=Default",
    ]
    if remote_debug_port is not None:
        command.append(f"--remote-debugging-port={remote_debug_port}")
    command.append(start_url)
    return command


def launch_command_payload(
    profile_dir: Path | str | None = None,
    *,
    start_url: str = DEFAULT_START_URL,
    workspace_root: Path | str = ".",
    remote_debug_port: int | None = None,
) -> dict[str, Any]:
    status = inspect_browser_profile(profile_dir, workspace_root=workspace_root).as_dict()
    if status["inside_workspace"]:
        return {
            "status": "blocked",
            "reason": "profile_inside_workspace",
            **status,
        }
    payload = {
        "status": "ready",
        **status,
        "start_url": start_url,
        "command": build_chrome_launch_command(
            profile_dir,
            start_url=start_url,
            remote_debug_port=remote_debug_port,
        ),
    }
    if remote_debug_port is not None:
        payload["remote_debug_port"] = remote_debug_port
        payload["browser_cdp_url"] = f"http://127.0.0.1:{remote_debug_port}"
    return payload


def write_json_line(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
