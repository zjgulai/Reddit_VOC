from __future__ import annotations

from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/smoke_local_insights_container.sh"
NGINX = (
    ROOT
    / "ref/UI/momcozy-reddit-workbench/deploy/insights/nginx.conf"
)


class LocalInsightsContainerSmokeTests(unittest.TestCase):
    def test_script_has_local_isolation_and_cleanup_contract(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        for marker in (
            "--release-dir PATH",
            "--output PATH",
            "CONTAINER_BASE_URL=\"http://127.0.0.1:8080\"",
            "--read-only",
            "--user 101:101",
            "--cap-drop ALL",
            "no-new-privileges:true",
            "--restart no",
            "--health-cmd",
            "http://127.0.0.1:8080/healthz",
            "--network",
            "--internal",
            "--pids-limit",
            "--memory",
            "--cpus",
            "production_unchanged",
            '"container_loopback_http": True',
            '"host_port_published": False',
            '"one_read_only_data_mount": True',
            '"exact_data_mount_contract": True',
            '"data_pointer_health": True',
            '"deploy": False',
            '"remote_write": False',
        ):
            self.assertIn(marker, source)
        for forbidden in (
            "docker system prune",
            "docker container prune",
            "docker image prune",
            "docker network prune",
            "docker stop $(",
            "docker rm $(",
            "--publish",
        ):
            self.assertNotIn(forbidden, source)

    def test_script_help_and_shell_syntax(self) -> None:
        syntax = subprocess.run(
            ["bash", "-n", str(SCRIPT)],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(syntax.returncode, 0, syntax.stderr)
        help_result = subprocess.run(
            [str(SCRIPT), "--help"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("local candidate only", help_result.stdout)

    def test_nginx_rejects_hidden_and_private_source_probes(self) -> None:
        source = NGINX.read_text(encoding="utf-8")
        for marker in (
            "location ~* ^/\\.env",
            "frontend-source-manifest",
            "candidate-ui-source-validation-receipt",
            "candidate-ui-validation-receipt",
            "release-manifest",
            "reddit_voc_site_snapshot_",
            "reddit_voc_insights_",
            "reddit_voc_reports_",
        ):
            self.assertIn(marker, source)


if __name__ == "__main__":
    unittest.main()
