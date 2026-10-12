"""Private local close requests; never carries profiles or login material."""

import os
import socket
from pathlib import Path


def request_toggle(path, message=b"close"):
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(0.3)
            client.connect(str(path))
            client.sendall(message)
        return True
    except OSError:
        return False


class ToggleServer:
    def __init__(self, path):
        self.path = Path(path)
        self.path.unlink(missing_ok=True)
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self.socket.bind(str(self.path))
            os.chmod(self.path, 0o600)
            self.socket.listen(4)
            self.socket.setblocking(False)
        except Exception:
            self.socket.close()
            self.path.unlink(missing_ok=True)
            raise

    def receive(self, close_window, toggle_window=None):
        try:
            connection, _ = self.socket.accept()
            with connection:
                connection.settimeout(0.1)
                message = connection.recv(64)
                if message == b"close":
                    close_window()
                elif toggle_window is not None:
                    parts = message.split()
                    if (
                        len(parts) == 3
                        and parts[0] == b"toggle"
                        and parts[1] in (b"top", b"bottom", b"left", b"right")
                        and parts[2].isdigit()
                    ):
                        toggle_window(parts[1].decode("ascii"), min(200, int(parts[2])))
        except OSError:
            pass
        return True

    def close(self):
        self.socket.close()
        self.path.unlink(missing_ok=True)
