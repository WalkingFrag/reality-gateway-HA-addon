import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "reality-gateway/rootfs/usr/local/lib"))

from reality_gateway.config import ExitSpec, ProbeTarget
from reality_gateway.probe import probe


class FakeSocket:
    def __init__(self):
        self.events = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def settimeout(self, value):
        pass

    def setsockopt(self, *args):
        self.events.append("mark")

    def connect(self, address):
        self.events.append("connect")

    def sendall(self, data):
        self.events.append("send")

    def recv(self, size):
        return b"HTTP/1.1 204 No Content\r\n\r\n"


class FakeContext:
    def __init__(self, sock):
        self.sock = sock

    def wrap_socket(self, sock, server_hostname):
        return self.sock


class ProbeTests(unittest.TestCase):
    def test_mark_is_set_before_connection(self):
        sock = FakeSocket()
        target = ProbeTarget("probe.example", "192.0.2.10", "/generate_204", 204)
        with patch("reality_gateway.probe.socket.socket", return_value=sock), patch(
            "reality_gateway.probe.ssl.create_default_context", return_value=FakeContext(sock)
        ):
            result = probe(ExitSpec("vless", "vless", 100), target, 101, 3)
        self.assertTrue(result)
        self.assertEqual(sock.events[:2], ["mark", "connect"])


if __name__ == "__main__":
    unittest.main()
