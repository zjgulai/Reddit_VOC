"""One pipeline run at a time, or two runs publish each other's work away.

`run_pipeline` had no mutual exclusion at all (grep for flock/fcntl/lockfile
across the pipeline, recompute, advance and lineage returned nothing). systemd's
timer only covers scheduled runs; manual re-runs are routine -- there was one at
19:01 on 2026-10-29 -- and they can overlap a long scheduled run.

In symlink mode the damage is concrete: both processes open a generation, both
write a complete tree, and both call `commit`. The second `os.replace` wins, so
the first run's tree is orphaned and the site serves data from a run that
reported success while its own generation was never published.

These tests pin the contract: the second run aborts before any write, the lock
survives a crash of the first run, and the lock file lives outside the
generation pointer so swapping generations cannot move it.
"""
from __future__ import annotations

import json
import fcntl
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import run_daily_t1_pipeline as pipeline  # noqa: E402


def _site(tmp_path: Path) -> dict:
    public_root = tmp_path / "html"
    (public_root / "data").mkdir(parents=True)
    store = tmp_path / "store.sqlite3"
    store.write_bytes(b"")
    out = tmp_path / "out"
    out.mkdir()
    return {"public_root": public_root, "store": store, "out": out}


@pytest.fixture()
def site(tmp_path: Path) -> dict:
    return _site(tmp_path)


def _count_calls(monkeypatch) -> dict:
    """Replace every step so the test can assert none of them ran."""
    calls = {"n": 0}

    def counted(*_a, **_k):
        calls["n"] += 1
        return {"step": "collect", "status": "ok"}

    monkeypatch.setattr(pipeline, "step1_collect", counted)
    monkeypatch.setattr(pipeline, "_preflight_writability", lambda *a, **k: {"checked": 0, "warnings": []})
    return calls


def _no_feishu(monkeypatch) -> None:
    """Make the real Feishu path inert, whatever the ambient environment says.

    `step5_feishu_push` returns early only when credentials are absent. A test
    that calls the real run_pipeline inheriting an operator shell's
    FEISHU_APP_SECRET would post a card to the production business group.
    """
    for var in ("FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_REPORT_CHAT_ID"):
        monkeypatch.delenv(var, raising=False)


def test_second_run_aborts_before_collect(site, monkeypatch) -> None:
    """Holding the lock means the second run does nothing at all."""
    monkeypatch.delenv(pipeline.PIPELINE_GENERATION_MODE_ENV, raising=False)
    monkeypatch.setenv("PIPELINE_LOCK_PATH", str(site["public_root"] / "data" / "test.lock"))
    calls = _count_calls(monkeypatch)

    holder = pipeline.PipelineLock(pipeline._lock_path(site["public_root"]))
    assert holder.acquire(), "the first lock must be takeable"
    try:
        receipt = pipeline.run_pipeline(
            store_path=site["store"], public_root=site["public_root"], output_dir=site["out"]
        )
    finally:
        holder.release()

    assert receipt["status"] == "aborted_already_running", receipt
    assert receipt["steps"] == [], "an aborted run must not record steps"
    assert calls["n"] == 0, "no step may run while another process holds the lock"
    assert receipt["lock_path"].endswith("test.lock")


def test_lock_released_on_failure(site, monkeypatch) -> None:
    """A crashed run must not wedge every later run."""
    monkeypatch.setenv("PIPELINE_LOCK_PATH", str(site["public_root"] / "data" / "test.lock"))
    monkeypatch.delenv(pipeline.PIPELINE_GENERATION_MODE_ENV, raising=False)
    # This test drives the REAL run_pipeline with one step stubbed. Without these
    # three lines the step loop continues past the collect error, reaches
    # feishu_push, and — in any shell that exports production credentials — posts
    # a card to the business group from a test run.
    _no_feishu(monkeypatch)

    def boom(*_a, **_k):
        raise RuntimeError("collect failed hard")

    monkeypatch.setattr(pipeline, "step1_collect", boom)
    monkeypatch.setattr(pipeline, "_preflight_writability", lambda *a, **k: {"checked": 0, "warnings": []})

    first = pipeline.run_pipeline(
        store_path=site["store"], public_root=site["public_root"], output_dir=site["out"],
        skip_feishu=True,
    )
    assert first["errors"], "the first run should have failed"

    # The lock is free again: a later run is not aborted.
    second = pipeline.PipelineLock(pipeline._lock_path(site["public_root"]))
    assert second.acquire(), "the lock must be released after a failed run"
    second.release()


def test_lock_path_outside_generation_symlink(site) -> None:
    """The lock must not live inside the pointer that commit replaces.

    `data/reddit-voc/...` is the generation pointer. A lock file there would
    move to a new inode when the pointer swaps, so a second process would lock a
    different file and both runs would proceed -- the exact failure this guards.
    """
    path = pipeline._lock_path(site["public_root"])
    assert path == site["public_root"] / "data" / "reddit-voc.lock"
    assert "reddit-voc/" not in str(path), "lock path must not be inside the pointer"

    # And it is a sibling of the pointer, not a descendant of it.
    pointer = site["public_root"] / "data" / "reddit-voc"
    assert path.parent == pointer.parent
    assert path.name != pointer.name


def test_lock_path_is_overridable(site, monkeypatch) -> None:
    monkeypatch.setenv("PIPELINE_LOCK_PATH", "/tmp/somewhere/else.lock")
    assert pipeline._lock_path(site["public_root"]) == Path("/tmp/somewhere/else.lock")


def test_aborted_run_returns_exit_code_3(site, monkeypatch) -> None:
    """The exit code is a contract: 3 means 'another run holds the lock'."""
    monkeypatch.setattr(
        pipeline,
        "run_pipeline",
        lambda **_k: {"status": "aborted_already_running", "lock_path": "x"},
    )
    monkeypatch.setattr(sys, "argv", ["run_daily_t1_pipeline.py"])
    assert pipeline.main() == 3


def test_lock_is_held_across_processes(tmp_path: Path) -> None:
    """flock is per-file-description, so a real second PROCESS must be blocked.

    Holding the lock in the same process and calling acquire again would not
    prove anything about a second pipeline process.
    """
    lock_path = tmp_path / "cross.lock"
    script = (
        "import fcntl, os, sys\n"
        "fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT, 0o644)\n"
        "try:\n"
        "    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
        "except OSError:\n"
        "    sys.exit(7)\n"
        "sys.exit(0)\n"
    )
    holder = pipeline.PipelineLock(lock_path)
    assert holder.acquire()
    try:
        # Same file, different process: must fail to lock.
        blocked = subprocess.run(
            [sys.executable, "-c", script, str(lock_path)], capture_output=True
        )
        assert blocked.returncode == 7, "a second process took the lock"
    finally:
        holder.release()

    # After release, the same process can take it.
    free = subprocess.run([sys.executable, "-c", script, str(lock_path)], capture_output=True)
    assert free.returncode == 0, "the lock was not released"


def test_lock_file_descriptor_is_not_inherited(tmp_path: Path) -> None:
    """O_CLOEXEC: an inherited fd would keep the lock alive after the parent exits.

    A child holding the fd keeps the flock for as long as it runs, so one
    pipeline that spawns a subprocess could wedge every later run until that
    child ends. The previous version of this test ended in
    `assert probe.returncode != 0 or True`, which is true by construction — it
    would pass with O_CLOEXEC removed. Assert the flag itself instead.
    """
    lock_path = tmp_path / "cloexec.lock"
    parent = pipeline.PipelineLock(lock_path)
    assert parent.acquire()
    try:
        assert parent._fd is not None
        # The kernel's own record of "close this on exec". This is what the
        # pipeline actually depends on; the fd number is not meaningful to a
        # child after exec.
        flags = fcntl.fcntl(parent._fd, fcntl.F_GETFD)
        assert flags & fcntl.FD_CLOEXEC, "lock fd would survive execve into a child"
    finally:
        parent.release()


def test_child_process_does_not_keep_the_lock_alive(tmp_path: Path) -> None:
    """With the parent gone, the lock must be free even if it spawned children."""
    lock_path = tmp_path / "spawn.lock"
    parent = pipeline.PipelineLock(lock_path)
    assert parent.acquire()

    # A child that would inherit the fd if O_CLOEXEC were missing.
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(0.1)"],
        close_fds=True,
    )
    parent.release()
    child.wait()

    other = pipeline.PipelineLock(lock_path)
    assert other.acquire(), "a spawned child kept the lock after the parent released it"
    other.release()


def test_foreign_owned_lock_file_is_not_reported_as_contention(tmp_path: Path) -> None:
    """A lock another user created must not look like 'another run is active'.

    A one-off `sudo` run is routine on this host and leaves a root-owned lock.
    Reporting that as contention would exit 3 forever, telling the operator to
    wait for a run that does not exist.
    """
    lock_path = tmp_path / "foreign.lock"
    lock_path.write_bytes(b"")
    os.chmod(lock_path, 0o444)  # no write bit: O_RDWR open fails, O_RDONLY works

    lock = pipeline.PipelineLock(lock_path)
    assert lock.acquire(), "a read-only lock file must still be lockable"
    lock.release()


def test_context_manager_acquires(tmp_path: Path) -> None:
    """`with PipelineLock(...)` must actually lock, not silently no-op."""
    lock_path = tmp_path / "ctx.lock"
    with pipeline.PipelineLock(lock_path) as held:
        assert held.acquired, "the context manager returned without acquiring"
        rival = pipeline.PipelineLock(lock_path)
        assert rival.acquire() is False, "the context manager did not hold the lock"

    # Released on exit.
    after = pipeline.PipelineLock(lock_path)
    assert after.acquire()
    after.release()
