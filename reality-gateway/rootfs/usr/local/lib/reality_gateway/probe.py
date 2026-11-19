"""HTTPS health probe forced through one policy-routing table."""

import socket
import ssl

from .config import ExitSpec, ProbeTarget


def probe(exit: ExitSpec, target: ProbeTarget, mark: int, timeout: float) -> bool:
    """Return success only for a verified response through a marked socket."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as raw:
            raw.settimeout(timeout)
            raw.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_MARK", 36), mark)
            raw.connect((target.ip, 443))
            context = ssl.create_default_context()
            with context.wrap_socket(raw, server_hostname=target.host) as secure:
                request = (
                    f"GET {target.path} HTTP/1.1\r\n"
                    f"Host: {target.host}\r\n"
                    "Connection: close\r\n\r\n"
                )
                secure.sendall(request.encode("ascii"))
                first = secure.recv(4096).split(b"\r\n", 1)[0]
                parts = first.split(b" ", 2)
                return (len(parts) >= 2 and parts[0] in (b"HTTP/1.0", b"HTTP/1.1")
                        and parts[1] == str(target.expected_status).encode())
    except (OSError, ssl.SSLError, ValueError, UnicodeError):
        return False
