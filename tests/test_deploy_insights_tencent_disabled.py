from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/deploy_insights_tencent.sh"


def test_legacy_direct_deploy_is_fail_closed_before_transport(tmp_path: Path) -> None:
    marker = tmp_path / "transport-called"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name in ("ssh", "scp"):
        executable = fake_bin / name
        executable.write_text(
            f"#!/bin/sh\n: > {marker!s}\nexit 99\n",
            encoding="utf-8",
        )
        executable.chmod(0o700)

    result = subprocess.run(
        ["/bin/bash", str(SCRIPT), "candidate.tgz"],
        text=True,
        capture_output=True,
        check=False,
        env={"PATH": str(fake_bin)},
    )

    assert result.returncode == 78
    assert "legacy direct deploy is disabled" in result.stderr
    assert "promote_insights_tencent.sh" in result.stderr
    assert not marker.exists()


def test_legacy_direct_deploy_has_valid_bash_syntax() -> None:
    result = subprocess.run(
        ["/bin/bash", "-n", str(SCRIPT)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
