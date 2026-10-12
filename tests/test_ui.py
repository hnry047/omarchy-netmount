"""UI behavior with synthetic profiles; never accesses stored connections or logins."""

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class PresentationTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(
            importlib.util.find_spec("nas_ui"), "Modern NAS UI missing"
        )
        import nas_ui

        self.ui = nas_ui

    def test_new_connection_does_not_prefill_a_personal_server(self):
        defaults = self.ui.new_connection("demo")
        for field in ("label", "server", "remote", "local"):
            self.assertEqual(defaults[field], "")
        self.assertEqual(defaults["id"], "demo")

    def test_status_messages_follow_connection_state(self):
        def conn(encrypt=True, remember_login=False):
            return {"encrypt": encrypt, "remember_login": remember_login}

        self.assertEqual(self.ui.status_messages([]), ["Add a share to get started"])
        mounted = self.ui.status_messages(
            [(conn(remember_login=True), "mounted"), (conn(), "unmounted")]
        )
        self.assertIn("1 share ready to open", mounted)
        self.assertIn("Traffic encrypted with SMB 3", mounted)
        self.assertIn("Mount a share from its ⋮ menu", mounted)
        self.assertIn("Logins kept in GNOME Keyring", mounted)
        plain = self.ui.status_messages([(conn(encrypt=False), "mounted")])
        self.assertIn("A mounted share is not encrypted", plain)
        self.assertNotIn("Traffic encrypted with SMB 3", plain)
        busy = self.ui.status_messages([(conn(), "occupied")])
        self.assertIn("A mount folder is in use", busy)

    def test_card_action_matches_actual_mount_state(self):
        self.assertEqual(self.ui.card_action("mounted"), ("Unmount", True))
        self.assertEqual(self.ui.card_action("unmounted"), ("Mount", True))
        self.assertEqual(self.ui.card_action("occupied"), ("Folder occupied", False))

    def test_busy_card_cannot_start_another_operation(self):
        self.assertEqual(self.ui.card_action("unmounted", busy=True), ("Mount", False))
        self.assertEqual(self.ui.card_action("mounted", busy=True), ("Unmount", False))

    def test_cold_start_loads_matching_gtk_and_gdk(self):
        plugin = Path(__file__).resolve().parents[1] / "src"
        result = subprocess.run(
            [
                "/usr/bin/python3",
                "-c",
                "from nas_app import load_gtk; Gtk, Gdk, GLib = load_gtk(); assert Gtk._version == '3.0'; assert Gdk._version == '3.0'",
            ],
            cwd=plugin,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


class FakeStyle:
    def __init__(self):
        self.classes = set()

    def add_class(self, name):
        self.classes.add(name)

    def remove_class(self, name):
        self.classes.discard(name)


class FakeLabel:
    def __init__(self):
        self.text, self.opacity, self.style = "", 1.0, FakeStyle()

    def set_text(self, text):
        self.text = text

    def set_opacity(self, value):
        self.opacity = value

    def get_style_context(self):
        return self.style


class FakeTimers:
    def __init__(self):
        self.pending = []

    def add(self, _ms, callback):
        self.pending.append(callback)

    def run(self, count):
        for _ in range(count):
            callback = self.pending.pop(0)
            if callback():
                self.pending.append(callback)

    def run_all(self):
        while self.pending:
            callback = self.pending.pop(0)
            if callback():
                self.pending.append(callback)


class StatusLineTests(unittest.TestCase):
    def setUp(self):
        import nas_ui

        self.label, self.timers = FakeLabel(), FakeTimers()
        self.line = nas_ui.StatusLine(self.label, self.timers.add)
        self.line.set_lines(["Ready to open", "Press Esc to close"])

    def test_rotation_shows_uppercase_lines_in_turn(self):
        self.assertEqual(self.label.text, "READY TO OPEN")
        self.line.advance()
        self.timers.run_all()
        self.assertEqual(self.label.text, "PRESS ESC TO CLOSE")
        self.assertEqual(self.label.opacity, 1)

    def test_error_is_red_pauses_rotation_then_clears(self):
        self.line.show("NAS login failed.", "error")
        self.assertEqual(self.label.text, "NAS login failed.")
        self.assertIn("error", self.label.style.classes)
        self.line.advance()
        self.assertEqual(self.label.text, "NAS login failed.")
        self.timers.run_all()
        self.assertEqual(self.label.text, "READY TO OPEN")
        self.assertNotIn("error", self.label.style.classes)

    def test_progress_stays_until_replaced(self):
        self.line.begin("Mounting…")
        self.assertEqual(self.timers.pending, [])
        self.line.end("Mounted.")
        self.assertNotIn("error", self.label.style.classes)
        self.timers.run_all()
        self.assertEqual(self.label.text, "READY TO OPEN")

    def test_notice_during_progress_returns_to_progress(self):
        self.line.begin("Mounting…")
        self.line.show("Wait for the current operation to finish before closing.")
        self.timers.run_all()
        self.assertEqual(self.label.text, "Mounting…")
        self.line.end("Mounted.")
        self.timers.run_all()
        self.assertEqual(self.label.text, "READY TO OPEN")

    def test_warning_is_highlighted_and_held_like_an_error(self):
        self.line.show("The keyring could not save the login.", "warning")
        self.assertIn("warning", self.label.style.classes)
        self.assertEqual(self.line.HOLD_MS["warning"], self.line.HOLD_MS["error"])

    def test_sentences_use_readable_notice_style_not_label_style(self):
        self.line.show("Mounted.")
        self.assertIn("notice", self.label.style.classes)
        self.timers.run_all()
        self.assertNotIn("notice", self.label.style.classes)

    def test_reset_drops_old_messages_when_the_window_hides(self):
        self.line.begin("Mounting…")
        self.line.show("NAS login failed.", "error")
        self.line.reset()
        self.assertEqual(self.label.text, "READY TO OPEN")
        self.assertNotIn("error", self.label.style.classes)
        self.timers.run_all()
        self.assertEqual(self.label.text, "READY TO OPEN")

    def test_fade_ends_on_the_current_lines(self):
        self.line.advance()
        self.timers.run(8)  # past the swap, partway into the fade-in
        self.line.set_lines(["Mount a share from its ⋮ menu", "2 shares ready"])
        self.timers.run_all()
        self.assertEqual(self.label.text, "2 SHARES READY")
        self.line.set_lines(["Add a share to get started"])
        self.assertEqual(self.label.text, "ADD A SHARE TO GET STARTED")

    def test_stale_timer_does_not_clear_a_newer_message(self):
        self.line.show("First problem.", "error")
        stale = self.timers.pending.pop()
        self.line.show("Second problem.", "error")
        stale()
        self.assertEqual(self.label.text, "Second problem.")


if __name__ == "__main__":
    unittest.main()
