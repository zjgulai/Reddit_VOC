import unittest

from reddit_voc.preflight import CheckResult, has_blocking_preflight_failure, local_doctor


class PreflightTests(unittest.TestCase):
    def test_local_doctor_has_no_network_marker(self):
        checks = local_doctor(no_network=True)
        network = [check for check in checks if check.name == "network"][0]
        self.assertEqual(network.status, "skipped")

    def test_blocking_preflight_failure_detects_missing_binary_or_dir(self):
        checks = [CheckResult(name="binary:example", status="missing", detail="not found")]
        self.assertTrue(has_blocking_preflight_failure(checks))


if __name__ == "__main__":
    unittest.main()
