#!/usr/bin/env python3
"""Read-only acceptance check for one Echo-Agent daily pipeline run.

Why this exists
---------------
Every morning the same questions are asked by hand: did the 07:05 run really
succeed, did it use the LLM, did product bindings land, is the pointer a
relative generation link, is the public `/data/` path serving the same bytes,
are the seven build stamps self-consistent, and is the freshness monitor green?
A 200 on `/` proves none of that: the SPA fallback returns 200 for an empty
site, and a browser/CDN cache can serve an old pointer for longer than its TTL.

This script collects evidence from the production host over SSH (read-only),
calls the existing `check_site_freshness.py` with `--no-notify` and a temporary
state path, then verifies the public bytes with a cache-busting request.

Exit codes
----------
0  every hard check passed
1  a hard failure (run/pointer/public/build stamp mismatch)
2  a finding: the data is serviceable but a known closure ticket is incomplete
   (e.g. build-receipts missing, receipt has no run_kind)
3  the check itself could not be evaluated (SSH/parse error)

The script never writes to the production tree. It writes only:
- `/tmp/echo-verify-freshness-<pid>.json` on the remote host (freshness state),
- the optional `--json-out` file on the machine that runs the check.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REMOTE_COLLECT = r"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

public_root = Path(os.environ.get("ECHO_PUBLIC_ROOT", "/opt/voc-report/html"))
output_root = Path(os.environ.get("ECHO_OUTPUT_ROOT", "/opt/echo-agent-bot/outputs"))
state_path = Path("/tmp/echo-verify-freshness-%d.json" % os.getpid())
voc = public_root / "data" / "reddit-voc"

out = {"public_root": str(public_root), "output_root": str(output_root)}

# --- systemd ---------------------------------------------------------------
def systemd_show(unit):
    try:
        raw = subprocess.check_output(
            ["systemctl", "show", unit, "-p", "Result", "-p", "ExecMainStatus",
             "-p", "ExecMainExitTimestamp", "-p", "ActiveState", "-p", "TimeoutStartUSec"],
            text=True, stderr=subprocess.DEVNULL, timeout=15,
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    parsed = {}
    for line in raw.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            parsed[key] = value
    return parsed

out["daily_service"] = systemd_show("echo-agent-daily.service")
out["daily_timer"] = systemd_show("echo-agent-daily.timer")
out["freshness_timer"] = systemd_show("echo-agent-freshness.timer")

# --- latest pipeline receipt ----------------------------------------------
receipts = sorted(
    (p for p in output_root.glob("*-pipeline-receipt.json") if p.is_file()),
    key=lambda p: p.name,
)
out["receipt_path"] = str(receipts[-1]) if receipts else None
if receipts:
    try:
        out["receipt"] = json.loads(receipts[-1].read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        out["receipt_error"] = str(exc)

# --- pointer and generations ----------------------------------------------
out["pointer"] = {
    "path": str(voc),
    "is_symlink": voc.is_symlink(),
    "exists": voc.exists(),
}
try:
    target = os.readlink(voc)
    out["pointer"]["link_target"] = target
    out["pointer"]["relative"] = not os.path.isabs(target)
except OSError as exc:
    out["pointer"]["link_target_error"] = str(exc)
try:
    out["pointer"]["resolved"] = str(voc.resolve(strict=True))
except Exception as exc:  # noqa: BLE001
    out["pointer"]["resolve_error"] = str(exc)

generations_root = public_root / "data" / "reddit-voc-generations"
try:
    out["generations"] = sorted(p.name for p in generations_root.iterdir() if p.is_dir())
except Exception as exc:  # noqa: BLE001
    out["generations"] = []
    out["generations_error"] = str(exc)

try:
    pointer_file = voc / "current-release.json"
    out["pointer_sha256"] = hashlib.sha256(pointer_file.read_bytes()).hexdigest()
    out["pointer_document"] = json.loads(pointer_file.read_text(encoding="utf-8"))
except Exception as exc:  # noqa: BLE001
    out["pointer_error"] = str(exc)

out["build_receipts_exists"] = (voc / "build-receipts").is_dir()

# --- existing freshness monitor -------------------------------------------
try:
    env = os.environ.copy()
    env["PYTHONPATH"] = "/opt/echo-agent-bot:/opt/echo-agent-bot/scripts"
    completed = subprocess.run(
        [sys.executable, "/opt/echo-agent-bot/scripts/check_site_freshness.py",
         "--public-root", str(public_root), "--state-path", str(state_path),
         "--no-notify"],
        cwd="/opt/echo-agent-bot", capture_output=True, text=True, env=env, timeout=90,
    )
    try:
        out["freshness"] = json.loads(completed.stdout)
    except Exception:  # noqa: BLE001
        out["freshness"] = {
            "error": "freshness_output_not_json",
            "returncode": completed.returncode,
            "stdout_tail": completed.stdout[-2000:],
            "stderr_tail": completed.stderr[-2000:],
        }
except Exception as exc:  # noqa: BLE001
    out["freshness"] = {"error": str(exc)}

# --- disk ------------------------------------------------------------------
try:
    usage = shutil.disk_usage(str(public_root))
    out["disk"] = {
        "total": usage.total,
        "used": usage.used,
        "free": usage.free,
        "free_percent": round(100.0 * usage.free / usage.total, 2) if usage.total else None,
    }
except Exception as exc:  # noqa: BLE001
    out["disk"] = {"error": str(exc)}

print(json.dumps(out, ensure_ascii=False))
"""

REQUIRED_STEPS = {
    "collect": {"success"},
    "begin_generation": {"ok"},
    "agents": {"ok"},
    "merge_snapshot": {"ok"},
    "recompute_derivatives": {"ok"},
    "advance_pointer": {"advanced"},
    "build_stamps": {"ok"},
    "commit_generation": {"committed"},
    "gc_generations": {"ok"},
    "feishu_push": {"sent"},
}


def _run_remote(args):
    if args.ssh_host:
        command = [
            "ssh",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=10",
            "-o", "StrictHostKeyChecking=accept-new",
        ]
        if args.ssh_key:
            command += ["-i", str(args.ssh_key), "-o", "IdentitiesOnly=yes"]
        command += [args.ssh_host, "python3", "-"]
        completed = subprocess.run(
            command, input=REMOTE_COLLECT, capture_output=True, text=True,
            timeout=args.timeout,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"remote collection failed ({completed.returncode}): "
                f"{completed.stderr.strip()[:2000]}"
            )
        return json.loads(completed.stdout)

    # On-server use: run the same collector locally.
    completed = subprocess.run(
        [sys.executable, "-"], input=REMOTE_COLLECT, capture_output=True,
        text=True, timeout=args.timeout, env=os.environ.copy(),
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"local collection failed ({completed.returncode}): "
            f"{completed.stderr.strip()[:2000]}"
        )
    return json.loads(completed.stdout)


def _fetch_public(url, timeout=20):
    separator = "&" if "?" in url else "?"
    request = urllib.request.Request(
        f"{url}{separator}cb={int(time.time() * 1000)}",
        headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
            return {
                "status": response.status,
                "content_type": response.headers.get("Content-Type", ""),
                "body": body,
                "sha256": hashlib.sha256(body).hexdigest(),
                "json": json.loads(body.decode("utf-8")),
            }
    except urllib.error.HTTPError as exc:
        return {"status": exc.code, "error": f"HTTP {exc.code}", "body": b""}
    except Exception as exc:  # noqa: BLE001
        return {"status": None, "error": str(exc), "body": b""}


class Report:
    def __init__(self):
        self.checks = []

    def add(self, status, check_id, detail):
        self.checks.append({"status": status, "id": check_id, "detail": detail})

    def counts(self):
        result = {"PASS": 0, "FAIL": 0, "FIND": 0, "WARN": 0, "SKIP": 0}
        for check in self.checks:
            result[check["status"]] = result.get(check["status"], 0) + 1
        return result

    def exit_code(self):
        if any(c["status"] == "FAIL" for c in self.checks):
            return 1
        if any(c["status"] == "FIND" for c in self.checks):
            return 2
        return 0


def _step_map(receipt):
    result = {}
    for step in receipt.get("steps") or []:
        if isinstance(step, dict) and step.get("step"):
            result[str(step["step"])] = step
    return result




def evaluate(data, public_url, public_enabled=True):
    report = Report()
    receipt = data.get("receipt") or {}
    steps = _step_map(receipt)
    pointer = data.get("pointer") or {}
    pointer_doc = data.get("pointer_document") or {}
    freshness = data.get("freshness") or {}
    service = data.get("daily_service") or {}
    timer = data.get("daily_timer") or {}

    run_id = str(receipt.get("run_id") or "unknown")

    # 1. systemd
    if service.get("Result") == "success" and service.get("ExecMainStatus") == "0":
        report.add("PASS", "systemd",
                   f"Result=success exit=0 at {service.get('ExecMainExitTimestamp', '?')}")
    elif service.get("error"):
        report.add("FAIL", "systemd", f"cannot read unit: {service['error']}")
    else:
        report.add("FAIL", "systemd",
                   f"Result={service.get('Result')} exit={service.get('ExecMainStatus')} "
                   f"at {service.get('ExecMainExitTimestamp')}")
    if timer.get("ActiveState") == "active":
        report.add("PASS", "daily_timer", "echo-agent-daily.timer active")
    else:
        report.add("FAIL", "daily_timer", f"timer state={timer.get('ActiveState')}")

    # 2. receipt and steps
    if not data.get("receipt_path"):
        report.add("FAIL", "receipt", "no *-pipeline-receipt.json found")
    elif receipt.get("status") == "success":
        report.add("PASS", "receipt", f"{run_id} status=success")
    else:
        report.add("FAIL", "receipt",
                   f"{run_id} status={receipt.get('status')} errors={receipt.get('errors')}")

    missing = [name for name in REQUIRED_STEPS if name not in steps]
    wrong = []
    for name, allowed in REQUIRED_STEPS.items():
        step = steps.get(name)
        if step is not None and str(step.get("status")) not in allowed:
            wrong.append(f"{name}={step.get('status')}")
    if missing:
        report.add("FAIL", "steps", f"missing steps: {', '.join(missing)}")
    elif wrong:
        report.add("FAIL", "steps", f"unexpected step status: {', '.join(wrong)}")
    else:
        report.add("PASS", "steps", "10/10 steps reached their success state")

    # 3. K1 identity: the closure metric requires a provable scheduled run.
    run_kind = receipt.get("run_kind")
    trigger = receipt.get("trigger")
    if run_kind is None:
        report.add("FIND", "k1_run_kind",
                   "receipt has no run_kind/trigger; K1 cannot distinguish scheduled "
                   "from manual runs (L6-T05/L6-T09)")
    elif str(run_kind) != "scheduled":
        report.add("WARN", "k1_run_kind", f"run_kind={run_kind}, not scheduled")
    else:
        report.add("PASS", "k1_run_kind", f"run_kind=scheduled trigger={trigger}")

    # 4. LLM path and evidence gate
    agents = steps.get("agents") or {}
    mode = agents.get("analysis_mode")
    gate = agents.get("evidence_gate") or {}
    if mode == "llm":
        report.add("PASS", "llm_mode",
                   f"analysis_mode=llm model={agents.get('llm_model')} "
                   f"gate={gate.get('checked')}/{gate.get('dropped')}/{gate.get('kept')}")
    elif mode:
        report.add("WARN", "llm_mode",
                   f"analysis_mode={mode} fallback={agents.get('llm_fallback_reason')}")
    else:
        report.add("WARN", "llm_mode", "agents step has no analysis_mode field")

    # 5. pointer and generations
    if pointer.get("is_symlink") and pointer.get("exists"):
        if pointer.get("relative"):
            report.add("PASS", "pointer", f"relative symlink -> {pointer.get('link_target')}")
        else:
            report.add("FAIL", "pointer",
                       f"absolute symlink -> {pointer.get('link_target')} "
                       "(dangles inside the nginx bind mount)")
    else:
        report.add("FAIL", "pointer", f"not a live symlink: {pointer}")

    generations = data.get("generations") or []
    if len(generations) >= 2:
        report.add("PASS", "generations", f"{len(generations)} kept: {', '.join(generations[-3:])}")
    else:
        report.add("WARN", "generations",
                   f"only {len(generations)} generation(s); no rollback target")

    # 6. freshness monitor (existing script)
    if freshness.get("error"):
        report.add("FAIL", "freshness", f"cannot evaluate: {freshness.get('error')}")
    else:
        failures = freshness.get("failures") or []
        state = freshness.get("state")
        if not failures and freshness.get("healthy"):
            report.add("PASS", "freshness", f"state={state} healthy")
        elif failures == ["build_receipt_missing"]:
            report.add("PASS", "freshness",
                       f"state={state}; only missing run-level receipt (tracked as L5-T04)")
        else:
            report.add("FAIL", "freshness", f"state={state} failures={failures}")
        datasets = freshness.get("datasets") or {}
        bad = [key for key, value in datasets.items() if not value.get("ok")]
        if bad:
            report.add("FAIL", "build_stamps", f"datasets failing self-proof: {', '.join(bad)}")
        elif datasets:
            report.add("PASS", "build_stamps", f"{len(datasets)}/7 datasets self-proved")
        status = freshness.get("freshness_status")
        if status == "partial":
            report.add("WARN", "freshness_status", "pointer freshness=partial (coverage gap)")
        elif status:
            report.add("PASS", "freshness_status", f"pointer freshness={status}")

    if not data.get("build_receipts_exists"):
        report.add("FIND", "l5_t04_build_receipts",
                   "build-receipts/ missing; L5-T04 run-level receipt not wired")
    else:
        report.add("PASS", "l5_t04_build_receipts", "build-receipts/ present")

    # 7. product bindings
    merge = steps.get("merge_snapshot") or {}
    if merge.get("product_resolver_loaded"):
        report.add("PASS", "product_bindings",
                   f"posts={merge.get('product_bound_posts')} "
                   f"comments={merge.get('product_bound_comments')} "
                   f"records={merge.get('product_bindings_total')}")
    elif merge:
        report.add("WARN", "product_bindings", "product resolver not loaded")
    if (merge.get("product_bindings_total") or 0) > 0 and not (
        (merge.get("product_bound_posts") or 0) + (merge.get("product_bound_comments") or 0)
    ):
        report.add("WARN", "product_bindings_counter",
                   "records>0 but bound posts/comments are both 0; check the counter")

    # 8. public bytes
    if public_enabled:
        public = _fetch_public(public_url)
        if public.get("status") != 200:
            report.add("FAIL", "public_http",
                       f"{public.get('status')} {public.get('error') or ''}")
        else:
            content_type = str(public.get("content_type") or "")
            if content_type.lower().startswith("application/json"):
                report.add("PASS", "public_content_type", content_type)
            else:
                report.add("FAIL", "public_content_type",
                           f"{content_type!r} (SPA fallback?)")
            public_doc = public.get("json") or {}
            public_freshness = public_doc.get("freshness") or {}
            if public.get("sha256") == data.get("pointer_sha256"):
                report.add("PASS", "public_bytes",
                           f"sha256 matches the generation pointer ({public.get('sha256')[:12]}…)")
            else:
                report.add("FAIL", "public_bytes",
                           f"public sha={str(public.get('sha256'))[:12]}… vs "
                           f"pointer sha={str(data.get('pointer_sha256'))[:12]}…; "
                           "retry with a cache-busting query before believing either side")
            if str(public_freshness.get("collector_run_id") or "") == run_id:
                report.add("PASS", "public_run_id", f"collector_run_id={run_id}")
            else:
                report.add("FAIL", "public_run_id",
                           f"public collector_run_id="
                           f"{public_freshness.get('collector_run_id')} vs receipt {run_id}")
            generated = public_doc.get("generated_at_utc")
            if generated:
                report.add("PASS", "public_generated_at", str(generated))
            else:
                report.add("FAIL", "public_generated_at",
                           "generated_at_utc is null; a cached or half-written pointer "
                           "is not evidence of a fresh publish")
            if str(public_freshness.get("data_as_of_utc") or "") == str(
                (pointer_doc.get("freshness") or {}).get("data_as_of_utc") or ""
            ):
                report.add("PASS", "public_data_as_of",
                           str(public_freshness.get("data_as_of_utc")))
    else:
        report.add("SKIP", "public", "--no-public")

    # 9. disk
    disk = data.get("disk") or {}
    if disk.get("free_percent") is not None:
        status = "WARN" if disk["free_percent"] < 10 else "PASS"
        report.add(status, "disk",
                   f"{disk['free_percent']}% free "
                   f"({disk['free'] // (1024**3)} GiB)")

    return report


def main():
    parser = argparse.ArgumentParser(
        description="Read-only acceptance check for one Echo-Agent daily run",
    )
    parser.add_argument("--ssh-host", help="user@host for the production host")
    parser.add_argument("--ssh-key", type=Path, help="SSH private key")
    parser.add_argument(
        "--public-base", default="https://radar.luteos.com",
        help="public site base URL",
    )
    parser.add_argument(
        "--public-url",
        default=None,
        help="override the full pointer URL (default: <base>/data/reddit-voc/current-release.json)",
    )
    parser.add_argument("--no-public", action="store_true", help="skip the HTTP check")
    parser.add_argument("--json-out", type=Path, help="write the full evidence JSON here")
    parser.add_argument("--timeout", type=int, default=120, help="SSH/collection timeout")
    args = parser.parse_args()

    try:
        data = _run_remote(args)
    except Exception as exc:  # noqa: BLE001
        print(f"UNEVALUABLE: {exc}", file=sys.stderr)
        return 3

    public_url = args.public_url or (
        args.public_base.rstrip("/") + "/data/reddit-voc/current-release.json"
    )
    report = evaluate(data, public_url, public_enabled=not args.no_public)

    receipt = data.get("receipt") or {}
    print(f"Echo daily run verification — {time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"host={args.ssh_host or 'local'} run_id={receipt.get('run_id', 'unknown')} "
          f"report_date={receipt.get('report_date', 'unknown')}")
    print()
    for check in report.checks:
        print(f"{check['status']:<4} {check['id']:<28} {check['detail']}")

    counts = report.counts()
    print()
    print("summary: " + " ".join(f"{key}={value}" for key, value in counts.items()))
    code = report.exit_code()
    print(f"result: {'OK' if code == 0 else 'FINDINGS' if code == 2 else 'FAILED'} "
          f"(exit {code})")

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(
                {"generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                 "public_url": public_url, "data": data,
                 "checks": report.checks, "summary": counts, "exit_code": code},
                ensure_ascii=False, indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        print(f"json: {args.json_out}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())