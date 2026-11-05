#!/usr/bin/env python3
"""Compute exactly which files a production run needs, from the imports themselves.

Why this exists
---------------
The deploy list was hand-written, and hand-written lists drift. Three separate
runs of this pipeline shipped an incomplete set:

  * `daily_release_transaction.py` — the whole transaction module was missing
    from the T08 list, so the first symlink run died on ImportError.
  * `observe_reddit_data_release.py` — imported by the freshness monitor.
  * `reddit_data_release_control.py` — imported by the module above it.

Each outage was the same shape: a module that exists locally, is imported at
runtime, and simply was not copied. Nothing detected it until production ran.

This tool derives the list from the import graph, so a new import is included
automatically. It also verifies an existing deployment against the same closure,
which is what makes "is production in sync?" answerable instead of a guess.

Usage:
    python3 scripts/deploy_manifest.py list                    # closure from entry points
    python3 scripts/deploy_manifest.py list --format json
    python3 scripts/deploy_manifest.py verify --remote-root /opt/echo-agent-bot

Exit codes: 0 in sync / 1 differences found / 2 tool error.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The programs production actually runs. Every runtime import reachable from
# these is required; anything else is a dev-only tool and is not deployed.
ENTRY_POINTS = (
    "scripts/run_daily_t1_pipeline.py",
    "scripts/check_site_freshness.py",
    # The two Feishu bot services run as their own systemd units and are not
    # imported by the pipeline; without being listed, none of their imports
    # (reply_engine, feishu_bot) would reach the deploy set — the same
    # incomplete-deploy shape this tool was built to prevent.
    "scripts/server_feishu_ws.py",
    "scripts/server_feishu_bot.py",
)

# Directories whose local modules are resolved by name (sibling imports).
# Mirrors the PYTHONPATH the systemd units set: the repo root, scripts/, src/.
SEARCH_PATHS = ("scripts", "src/reddit_voc", "tools/feishu-card/builders")

# Never deploy: tests, caches, build artifacts.
EXCLUDED_PREFIXES = (
    "tests/",
    "ref/",
    "docs/",
    "outputs/",
    "__pycache__/",
    ".venv/",
)

# Local path prefix -> deployed path prefix.
#
# The two layouts differ, and this matters: the systemd units set
# PYTHONPATH=/opt/echo-agent-bot:/opt/echo-agent-bot/scripts, so `import
# reddit_voc` on the server resolves to /opt/echo-agent-bot/reddit_voc. The
# repository keeps the same package at src/reddit_voc (the pipeline inserts
# ROOT/"src" onto sys.path locally). Verifying src/reddit_voc against
# /opt/echo-agent-bot/src/reddit_voc would compare a copy nothing imports and
# report a stale top-level package as "in sync" — the exact class of miss this
# tool exists to prevent.
REMOTE_PATH_MAP = (
    ("src/reddit_voc/", "reddit_voc/"),
)


def remote_path(rel: str) -> str:
    """Map a repo-relative path to the path the deployed tree actually uses."""
    for local_prefix, remote_prefix in REMOTE_PATH_MAP:
        if rel.startswith(local_prefix):
            return remote_prefix + rel[len(local_prefix):]
    return rel


class ManifestError(RuntimeError):
    pass


def _module_file(name: str, *, from_path: Path | None = None) -> Path | None:
    """Resolve an imported module name to a local file, if it is local.

    Third-party and stdlib names resolve to nothing and are skipped: they are
    installed on the server, not copied from here.
    """
    leaf = name.split(".")[0]

    # `from scripts import x` / `import scripts.x` resolves under scripts/.
    if leaf == "scripts":
        rest = name.split(".")[1:]
        if rest:
            candidate = ROOT / "scripts" / Path(*rest).with_suffix(".py")
            if candidate.is_file():
                return candidate
        return None

    # `from reddit_voc...` — the package lives at src/reddit_voc AND, on the
    # server, at /opt/echo-agent-bot/reddit_voc. Both are real layouts here.
    candidate = ROOT / "src" / Path(*name.split(".")).with_suffix(".py")
    if candidate.is_file():
        return candidate
    package_init = ROOT / "src" / Path(*name.split(".")) / "__init__.py"
    if package_init.is_file():
        return package_init

    # Sibling module: the import machinery searches each sys.path entry, and for
    # a script run directly that entry is its own directory.
    for base in SEARCH_PATHS:
        candidate = ROOT / base / Path(*name.split(".")).with_suffix(".py")
        if candidate.is_file():
            return candidate
        package_init = ROOT / base / Path(*name.split(".")) / "__init__.py"
        if package_init.is_file():
            return package_init

    if from_path is not None:
        sibling = from_path.parent / Path(*name.split(".")).with_suffix(".py")
        if sibling.is_file():
            return sibling

    return None


def _imports_of(path: Path) -> tuple[list[str], list[Path]]:
    """What one file imports: (module names, already-resolved local paths).

    AST rather than a regex: a string containing "import x" in a docstring or a
    prompt is not an import, and this codebase is full of Chinese prompts that
    mention tooling by name.

    Relative imports return resolved PATHS, not names. An earlier version turned
    `from .batch_runner import X` into the dotted name
    `src.reddit_voc.agents.batch_runner`, which no module search path can
    resolve — so every relative import was silently dropped. The closure then
    missed `agents/batch_runner.py`, `contracts.py`, `rnd_voc.py` and
    `content_scout.py`: the tool reproduced the exact bug it was written to
    catch.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as exc:
        raise ManifestError(f"cannot parse {path}: {exc}") from exc

    names: list[str] = []
    resolved: list[Path] = []

    def _resolve_relative(base: Path, module: str | None, alias: str | None) -> None:
        """Resolve `.x` / `from . import x` against the file's own package."""
        if module:
            pieces = Path(*module.split("."))
            for candidate in (
                base / pieces.with_suffix(".py"),
                base / pieces / "__init__.py",
            ):
                if candidate.is_file():
                    resolved.append(candidate)
                    break
            else:
                # The module part is not local; the alias may still be.
                if alias:
                    for candidate in (
                        base / pieces / Path(alias).with_suffix(".py"),
                        base / pieces / alias / "__init__.py",
                    ):
                        if candidate.is_file():
                            resolved.append(candidate)
                            break
            return

        # `from . import x` — every alias is a sibling module or package.
        if alias:
            for candidate in (
                base / Path(alias).with_suffix(".py"),
                base / alias / "__init__.py",
            ):
                if candidate.is_file():
                    resolved.append(candidate)
                    break

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)

        elif isinstance(node, ast.ImportFrom):
            if node.level:
                # level=1 means the file's own directory; each extra dot goes up.
                base = path.parent
                for _ in range(node.level - 1):
                    base = base.parent
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    _resolve_relative(base, node.module, alias.name)
                continue

            if node.module:
                names.append(node.module)
                # `from pkg import module` — the alias may itself be a module.
                for alias in node.names:
                    names.append(f"{node.module}.{alias.name}")

    return names, resolved


def closure() -> dict[str, Path]:
    """Every local file reachable from the entry points, keyed by repo path."""
    required: dict[str, Path] = {}
    queue: list[Path] = []

    for entry in ENTRY_POINTS:
        path = ROOT / entry
        if not path.is_file():
            raise ManifestError(f"entry_point_missing:{entry}")
        required[entry] = path
        queue.append(path)

    while queue:
        current = queue.pop()
        names, already_resolved = _imports_of(current)
        candidates = list(already_resolved)
        for name in names:
            resolved = _module_file(name, from_path=current)
            if resolved is None:
                continue
            candidates.append(resolved)
        for resolved in candidates:
            if resolved is None:
                continue
            try:
                key = str(resolved.relative_to(ROOT))
            except ValueError:
                continue
            if any(key.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
                continue
            if key in required:
                continue
            required[key] = resolved
            queue.append(resolved)

    return dict(sorted(required.items()))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(remote_root: Path) -> list[dict]:
    """Compare the closure against a deployed tree.

    Compares bytes, not mtimes: a copied file keeps its mtime, and mtime
    differences on identical bytes would drown the real signal.
    """
    differences: list[dict] = []
    for rel, local in closure().items():
        # Compare against the path the deployed tree actually uses; see
        # REMOTE_PATH_MAP for why src/reddit_voc is not the served package.
        remote = remote_root / remote_path(rel)
        if not remote.is_file():
            differences.append({"path": rel, "remote": remote_path(rel),
                                "issue": "missing_on_remote"})
            continue
        if sha256(remote) != sha256(local):
            differences.append({"path": rel, "remote": remote_path(rel),
                                "issue": "content_differs"})
    return differences


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    list_cmd = sub.add_parser("list", help="print the required file set")
    list_cmd.add_argument("--format", choices=("text", "json"), default="text")

    verify_cmd = sub.add_parser("verify", help="compare a deployed tree to the closure")
    verify_cmd.add_argument("--remote-root", type=Path, required=True)
    verify_cmd.add_argument("--format", choices=("text", "json"), default="text")

    args = parser.parse_args()

    try:
        if args.command == "list":
            files = closure()
            if args.format == "json":
                print(json.dumps(
                    {rel: {"sha256": sha256(p), "bytes": p.stat().st_size}
                     for rel, p in files.items()},
                    ensure_ascii=False, indent=2,
                ))
            else:
                for rel, path in files.items():
                    print(f"{rel}\t{sha256(path)[:16]}\t{path.stat().st_size}")
                print(f"# {len(files)} files", file=sys.stderr)
            return 0

        differences = verify(args.remote_root)
        if args.format == "json":
            print(json.dumps({"in_sync": not differences, "differences": differences},
                             ensure_ascii=False, indent=2))
        else:
            if not differences:
                print("in sync")
            for d in differences:
                print(f"{d['issue']}\t{d['path']}")
        return 0 if not differences else 1

    except ManifestError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
