import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class ToggleTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(
            importlib.util.find_spec("nas_toggle"), "Icon toggle implementation missing"
        )
        import nas_toggle

        self.toggle = nas_toggle
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "manager.sock"

    def test_second_click_requests_close_and_socket_is_private(self):
        server = self.toggle.ToggleServer(self.path)
        self.addCleanup(server.close)
        requested = []
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertTrue(self.toggle.request_toggle(self.path))
        server.receive(lambda: requested.append("close"))
        self.assertEqual(requested, ["close"])

    def test_warm_request_does_not_close_and_toggle_passes_only_geometry(self):
        server = self.toggle.ToggleServer(self.path)
        self.addCleanup(server.close)
        calls = []

        def close():
            calls.append("close")

        def toggle(edge, size):
            calls.append((edge, size))

        self.assertTrue(self.toggle.request_toggle(self.path, b"warm"))
        server.receive(close, toggle)
        self.assertEqual(calls, [])
        self.assertTrue(self.toggle.request_toggle(self.path, b"toggle left 28"))
        server.receive(close, toggle)
        self.assertEqual(calls, [("left", 28)])
        self.assertTrue(self.toggle.request_toggle(self.path, b"toggle invalid 28"))
        server.receive(close, toggle)
        self.assertEqual(calls, [("left", 28)])

    def test_no_open_window_allows_a_new_one(self):
        self.assertFalse(self.toggle.request_toggle(self.path))

    def test_exit_removes_socket(self):
        server = self.toggle.ToggleServer(self.path)
        server.close()
        self.assertFalse(self.path.exists())


class ToggleErrorTests(unittest.TestCase):
    def setUp(self):
        import nas_toggle

        self.toggle = nas_toggle
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_bind_failure_closes_the_socket_and_raises(self):
        missing = Path(self.tmp.name) / "no-such-dir" / "manager.sock"
        with self.assertRaises(OSError):
            self.toggle.ToggleServer(missing)
        self.assertFalse(missing.exists())

    def test_receive_with_nothing_pending_keeps_watching(self):
        server = self.toggle.ToggleServer(Path(self.tmp.name) / "manager.sock")
        self.addCleanup(server.close)
        calls = []
        self.assertTrue(server.receive(lambda: calls.append("close")))
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
