from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts/run_v2_daily_pipeline.sh"


class V2DailyPipelineWrapperTests(unittest.TestCase):
    def test_orchestration_observation_is_taken_after_quiescence_wait(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        capture = root / "observed-at.txt"
        fake_python = bin_dir / "python3"
        fake_python.write_text(
            """#!/bin/sh
set -eu
if [ "${1:-}" = "-c" ]; then
  exec "$REAL_PYTHON" "$@"
fi
case " $* " in
  *" run-comment-refresh "*)
    batch_root=""
    run_id=""
    while [ "$#" -gt 0 ]; do
      case "$1" in
        --source-batch-root) shift; batch_root="$1" ;;
        --run-id) shift; run_id="$1" ;;
      esac
      shift
    done
    mkdir -p "$batch_root/$run_id"
    : > "$batch_root/$run_id/source-batch-manifest.json"
    ;;
  *"validate_reddit_source_batch.py "*)
    output=""
    while [ "$#" -gt 0 ]; do
      case "$1" in
        --output) shift; output="$1" ;;
      esac
      shift
    done
    mkdir -p "$(dirname "$output")"
    : > "$output"
    ;;
  *"orchestrate_reddit_v2_candidate.py "*)
    observed=""
    while [ "$#" -gt 0 ]; do
      case "$1" in
        --observed-at-utc) shift; observed="$1" ;;
      esac
      shift
    done
    printf '%s\n' "$observed" > "$OBSERVED_CAPTURE"
    ;;
  *)
    echo "unexpected fake python invocation: $*" >&2
    exit 99
    ;;
esac
""",
            encoding="utf-8",
        )
        fake_python.chmod(0o700)
        output_root = root / "v2-output"
        environment = os.environ.copy()
        environment.update(
            {
                "OBSERVED_CAPTURE": str(capture),
                "PATH": f"{bin_dir}:{environment['PATH']}",
                "REAL_PYTHON": sys.executable,
                "V2_QUIESCENCE_SECONDS": "1",
            }
        )
        completed = subprocess.run(
            [
                "bash",
                str(WRAPPER),
                str(root / "daily-manifest.json"),
                str(root / "daily-receipt.json"),
                str(root / "center.sqlite3"),
                str(output_root),
                "refresh-test",
                "2026-07-16T23:00:00Z",
                "2026-07-17T23:00:00Z",
                "2026-07-17T23:00:00Z",
            ],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        observed = datetime.fromisoformat(
            capture.read_text(encoding="utf-8").strip().replace("Z", "+00:00")
        )
        self.assertGreater(observed, datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.assertLessEqual(observed, datetime.now(timezone.utc))


if __name__ == "__main__":
    unittest.main()
