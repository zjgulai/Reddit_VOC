from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "task31ac_readonly_acceptance_execute_once.sh"


class Task31ACReadonlyAcceptanceExecuteOnceTests(unittest.TestCase):
    def _run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(SCRIPT), *arguments],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

    def _network_files(self, root: Path, interfaces: list[str], routes: int) -> tuple[Path, Path]:
        net_dev = root / "net-dev"
        route = root / "route"
        net_dev.write_text(
            "Inter-|   Receive                                                |  Transmit\n"
            " face |bytes packets errs drop fifo frame compressed multicast|bytes packets errs drop fifo colls carrier compressed\n"
            + "".join(f"{name}: 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n" for name in interfaces),
            encoding="utf-8",
        )
        route.write_text(
            "Iface Destination Gateway Flags RefCnt Use Metric Mask MTU Window IRTT\n"
            + "".join(f"eth0 00000000 00000000 0000 0 0 {index} 00000000 0 0 0\n" for index in range(routes)),
            encoding="utf-8",
        )
        return net_dev, route

    def test_shell_syntax_and_single_verifier_exec(self) -> None:
        syntax = subprocess.run(
            ["bash", "-n", str(SCRIPT)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        source = SCRIPT.read_text(encoding="utf-8")

        self.assertEqual(syntax.returncode, 0, syntax.stderr)
        self.assertEqual(source.count('exec python3 "$VERIFIER"'), 1)
        self.assertNotIn("/sys/class/net", source)
        self.assertIn("validate_network_none /proc/net/dev /proc/net/route", source)
        self.assertIn('readonly_bind Task31AB "$TASK31AB"', source)

    def test_namespace_aware_loopback_only_gate_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            net_dev, route = self._network_files(Path(temporary), ["lo"], 0)

            completed = self._run("--self-test-network-gate", str(net_dev), str(route))

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("NETWORK_NONE_GATE=passed interfaces=lo routes=0", completed.stderr)

    def test_non_loopback_interface_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            net_dev, route = self._network_files(Path(temporary), ["eth0", "lo"], 0)

            completed = self._run("--self-test-network-gate", str(net_dev), str(route))

        self.assertEqual(completed.returncode, 70)
        self.assertIn("FAIL_CLOSED:network_interfaces_invalid_eth0 lo", completed.stderr)

    def test_route_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            net_dev, route = self._network_files(Path(temporary), ["lo"], 1)

            completed = self._run("--self-test-network-gate", str(net_dev), str(route))

        self.assertEqual(completed.returncode, 70)
        self.assertIn("FAIL_CLOSED:network_routes_nonzero_1", completed.stderr)

    def test_receipt_search_survives_final_nonmatching_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected_payload = b"bound-execution-receipt"
            expected = hashlib.sha256(expected_payload).hexdigest()
            (root / "00-match.json").write_bytes(expected_payload)
            for index in range(1, 8):
                (root / f"{index:02d}-nonmatch.json").write_bytes(f"other-{index}".encode())
            find_order = subprocess.run(
                ["find", str(root), "-xdev", "-type", "f", "-print0"],
                check=True,
                capture_output=True,
            ).stdout.split(b"\0")
            self.assertNotEqual(
                hashlib.sha256(Path(find_order[-2].decode()).read_bytes()).hexdigest(),
                expected,
            )

            completed = self._run("--self-test-receipt-loop", str(root), expected)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(completed.stdout.rstrip().endswith("00-match.json"))


if __name__ == "__main__":
    unittest.main()
