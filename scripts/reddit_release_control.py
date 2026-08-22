#!/usr/bin/env python3
"""Shared local primitives for the Reddit VOC release-control contracts.

This module is deliberately side-effect narrow: it can only reopen local files
below an explicit root and create one immutable mode-0600 JSON document.  It
does not import subprocess, open a network connection, or perform a production
operation.
"""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping, NoReturn

try:
    from scripts import build_reddit_promotion_packet as packet_contract
except ModuleNotFoundError:  # Direct ``python scripts/...`` execution.
    import build_reddit_promotion_packet as packet_contract


class ReleaseControlError(ValueError):
    """A local release-control artifact failed its closed contract."""


def canonical_bytes(value: object) -> bytes:
    """Return the on-disk canonical JSON form used by control artifacts."""

    return packet_contract.canonical_file_bytes(value)


def sha256_bytes(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def require_sha256(value: object, *, label: str) -> str:
    try:
        return packet_contract.require_sha256(value, label=label)
    except packet_contract.PromotionPacketError as exc:
        raise ReleaseControlError(str(exc)) from exc


def parse_utc(value: object, *, label: str) -> tuple[str, datetime]:
    try:
        return packet_contract.parse_utc(value, label=label)
    except packet_contract.PromotionPacketError as exc:
        raise ReleaseControlError(str(exc)) from exc


def require_root(path: Path) -> Path:
    try:
        return packet_contract._require_root(path)
    except packet_contract.PromotionPacketError as exc:
        raise ReleaseControlError(str(exc)) from exc


def read_file(
    *,
    root: Path,
    path: Path,
    label: str,
    expected_mode: int | None = None,
) -> tuple[str, bytes]:
    try:
        return packet_contract.read_explicit_file(
            root, path, label=label, expected_mode=expected_mode
        )
    except packet_contract.PromotionPacketError as exc:
        raise ReleaseControlError(str(exc)) from exc


def load_json_bytes(
    payload: bytes,
    *,
    label: str,
    canonical_required: bool = True,
) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseControlError(f"{label}_invalid_json") from exc
    if not isinstance(value, dict):
        raise ReleaseControlError(f"{label}_not_object")
    if canonical_required and payload != canonical_bytes(value):
        raise ReleaseControlError(f"{label}_noncanonical")
    return value


def read_json(
    *,
    root: Path,
    path: Path,
    label: str,
    expected_mode: int | None = 0o600,
    expected_sha256: str | None = None,
) -> tuple[str, bytes, dict[str, Any]]:
    relative, payload = read_file(
        root=root, path=path, label=label, expected_mode=expected_mode
    )
    if expected_sha256 is not None:
        expected = require_sha256(expected_sha256, label=f"expected_{label}_sha256")
        if sha256_bytes(payload) != expected:
            raise ReleaseControlError(f"{label}_sha256_mismatch")
    return relative, payload, load_json_bytes(payload, label=label)


def write_immutable(
    *, root: Path, output: Path, value: Mapping[str, Any], label: str
) -> str:
    """Create ``output`` once, or return ``no_change`` for identical bytes."""

    try:
        return packet_contract.write_immutable_packet(root, output, value)
    except packet_contract.PromotionPacketError as exc:
        message = str(exc).replace("promotion_packet", label)
        raise ReleaseControlError(message) from exc


def require_bool(value: object, expected: bool, *, label: str) -> None:
    if value is not expected:
        raise ReleaseControlError(f"{label}_invalid")


def require_nonnegative_int(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ReleaseControlError(f"{label}_invalid")
    return value


def require_string(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReleaseControlError(f"{label}_invalid")
    return value


def fail_with_release_error(exc: Exception, target: type[ValueError]) -> NoReturn:
    raise target(str(exc)) from exc

