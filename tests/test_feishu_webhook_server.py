import json
import threading
import unittest
import urllib.request

from reddit_voc.feishu_webhook_server import create_feishu_server


class FeishuWebhookServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = create_feishu_server(host="127.0.0.1", port=18399)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_url_verification_handshake(self):
        url = "http://127.0.0.1:18399/webhook/feishu"
        payload = json.dumps({"type": "url_verification", "challenge": "test_challenge_code"}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data.get("challenge"), "test_challenge_code")


if __name__ == "__main__":
    unittest.main()
