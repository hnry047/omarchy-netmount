"""Render GTK widgets with synthetic data; no NAS or keyring access."""

import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Bound even without GTK, so modules importing it (and type checkers) see it.
Gtk: Any = None
try:
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk  # type: ignore  # generated at runtime

    AVAILABLE = Gtk.init_check()[0]
except ImportError:
    AVAILABLE = False


@unittest.skipUnless(
    AVAILABLE, "GTK display required; run with the system Python in a desktop session"
)
class GtkUiTests(unittest.TestCase):
    def test_live_second_invocation_closes_the_manager(self):
        # Use an isolated synthetic profile and lock/socket namespace, never
        # the installed manager's saved profiles or remembered login.
        plugin = Path(__file__).resolve().parents[1] / "src"
        with tempfile.TemporaryDirectory() as directory:
            code = "import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); import nas_app; nas_app.PROFILE_PATH=Path(sys.argv[2])/'profiles.json'; nas_app.MANAGER_LOCK_PATH=Path(sys.argv[2])/'manager.lock'; nas_app.main()"
            args = ["/usr/bin/python3", "-c", code, str(plugin), directory]
            child = subprocess.Popen(
                args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            try:
                socket_path = Path(directory) / "manager.sock"
                deadline = time.monotonic() + 5
                while (
                    not socket_path.exists()
                    and child.poll() is None
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.02)
                self.assertTrue(
                    socket_path.exists(), "NAS manager did not finish opening"
                )
                second = subprocess.run(
                    args,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=3,
                )
                self.assertEqual(second.returncode, 0)
                self.assertEqual(child.wait(timeout=3), 0)
                self.assertFalse(socket_path.exists())
            finally:
                if child.poll() is None:
                    child.terminate()
                    child.wait(timeout=3)

    def test_preloaded_process_opens_and_hides_without_restarting(self):
        import json

        from nas_geometry import ipc
        from nas_toggle import request_toggle

        plugin = Path(__file__).resolve().parents[1] / "src"
        with tempfile.TemporaryDirectory() as directory:
            code = "import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); import nas_app; nas_app.PROFILE_PATH=Path(sys.argv[2])/'profiles.json'; nas_app.MANAGER_LOCK_PATH=Path(sys.argv[2])/'manager.lock'; sys.argv=['nas_app.py','--preload','--bar-position','left']; nas_app.main()"
            child = subprocess.Popen(
                ["/usr/bin/python3", "-c", code, str(plugin), directory],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            socket_path = Path(directory) / "manager.sock"

            def shown():
                return any(
                    c["pid"] == child.pid and c["title"] == "Netmount"
                    for c in json.loads(ipc("clients", "-j"))
                )

            def wait_for(predicate):
                deadline = time.monotonic() + 4
                while time.monotonic() < deadline and child.poll() is None:
                    if predicate():
                        return
                    time.sleep(0.01)
                self.fail("Preloaded NAS window did not reach the expected state")

            try:
                wait_for(socket_path.exists)
                self.assertFalse(shown(), "Preloading must not display a window")
                for _ in range(2):
                    self.assertTrue(request_toggle(socket_path, b"toggle left 28"))
                    wait_for(shown)
                    self.assertIsNone(child.poll())
                    self.assertTrue(request_toggle(socket_path, b"toggle left 28"))
                    wait_for(lambda: not shown())
                    self.assertIsNone(child.poll())
            finally:
                if child.poll() is None:
                    child.terminate()
                child.wait(timeout=4)
            self.assertFalse(socket_path.exists())

    def test_resident_close_clears_session_memory_but_busy_close_does_not(self):
        import nas_app

        with tempfile.TemporaryDirectory() as directory:

            def inspect():
                window = next(
                    w
                    for w in Gtk.Window.list_toplevels()
                    if w.get_title() == "Netmount"
                )
                self.assertFalse(window.get_visible())
                window.manager.session_logins["demo"] = object()
                window.manager.profiles.append({"id": "demo"})
                window.busy = True
                self.assertTrue(window.on_delete())
                self.assertIn("demo", window.manager.session_logins)
                window.busy = False
                self.assertTrue(window.on_delete())
                self.assertEqual(window.manager.session_logins, {})
                self.assertEqual(window.manager.profiles, [])
                window.destroy()

            with (
                patch.object(
                    nas_app, "PROFILE_PATH", Path(directory) / "profiles.json"
                ),
                patch.object(
                    nas_app, "MANAGER_LOCK_PATH", Path(directory) / "manager.lock"
                ),
                patch.object(
                    sys, "argv", ["nas_app.py", "--preload", "--bar-position", "left"]
                ),
                patch.object(Gtk, "main", inspect),
                patch.object(Gtk, "main_quit"),
            ):
                nas_app.main()

    def widgets(self, parent):
        yield parent
        if isinstance(parent, Gtk.Container):
            for child in parent.get_children():
                yield from self.widgets(child)

    def test_live_row_menu_and_details_remain_open(self):
        from gi.repository import GLib  # type: ignore  # generated at runtime

        import nas_app
        from nas_manager import Manager

        with tempfile.TemporaryDirectory() as folder:
            manager = Manager(
                Path(folder) / "profiles.json", object(), mounts_fn=lambda: []
            )
            manager.profiles.append(
                dict(
                    id="demo",
                    label="Documents",
                    server="fileserver",
                    remote="shared",
                    source="//fileserver/shared",
                    local="/mnt/demo",
                )
            )
            real_main = Gtk.main
            failures = []

            def run_main():
                window = next(
                    w
                    for w in Gtk.Window.list_toplevels()
                    if w.get_title() == "Netmount"
                )

                def open_menu():
                    button = next(
                        w for w in self.widgets(window) if isinstance(w, Gtk.MenuButton)
                    )
                    if button.get_popover().get_visible():
                        failures.append(
                            AssertionError(
                                "Dropdown opened before its button was clicked"
                            )
                        )
                    button.set_active(True)
                    details = next(
                        w
                        for w in self.widgets(button.get_popover())
                        if isinstance(w, Gtk.Expander)
                    )
                    details.set_expanded(True)

                    def inspect():
                        try:
                            self.assertTrue(window.get_visible())
                            self.assertTrue(button.get_popover().get_mapped())
                            self.assertTrue(details.get_child().get_mapped())
                        except Exception as exc:
                            failures.append(exc)
                        finally:
                            window.destroy()
                        return False

                    GLib.timeout_add(350, inspect)
                    return False

                GLib.timeout_add(350, open_menu)
                real_main()

            with (
                patch("nas_manager.Manager", return_value=manager),
                patch.object(nas_app, "read_mounts", return_value=[]),
                patch.object(nas_app, "PROFILE_PATH", Path(folder) / "profiles.json"),
                patch.object(
                    nas_app, "MANAGER_LOCK_PATH", Path(folder) / "manager.lock"
                ),
                patch.object(Gtk, "main", run_main),
            ):
                nas_app.main()
            if failures:
                raise failures[0]

    def test_manager_empty_state_and_editor_are_usable(self):
        import nas_app
        from nas_manager import Manager

        class FakeKeyring:
            def get_login(self, *_):
                raise AssertionError("UI rendering must not access the keyring")

        with tempfile.TemporaryDirectory() as home:
            manager = Manager(
                Path(home) / "profiles.json", FakeKeyring(), mounts_fn=lambda: []
            )
            observed = []
            chosen_folder = Path(home) / "selected-folder"
            chosen_folder.mkdir()
            real_dialog_run = Gtk.Dialog.run

            def inspect_editor(dialog):
                if isinstance(dialog, Gtk.FileChooserDialog):
                    from gi.repository import GLib  # type: ignore  # generated at runtime

                    dialog.set_current_folder(str(chosen_folder))
                    failures = []

                    def choose_folder():
                        try:
                            button = dialog.get_widget_for_response(Gtk.ResponseType.OK)
                            self.assertTrue(
                                button.get_mapped(),
                                "Choose button must be visible on screen",
                            )
                            self.assertGreater(button.get_allocation().width, 1)
                            self.assertTrue(button.get_sensitive())
                            button.clicked()
                        except Exception as exc:
                            failures.append(exc)
                            dialog.response(Gtk.ResponseType.CANCEL)
                        return False

                    GLib.timeout_add(500, choose_folder)
                    answer = real_dialog_run(dialog)
                    if failures:
                        raise failures[0]
                    return answer
                entries = [w for w in self.widgets(dialog) if isinstance(w, Gtk.Entry)]
                self.assertEqual(len(entries), 7)
                self.assertTrue(all(w.get_text() == "" for w in entries))
                password = next(
                    w
                    for w in entries
                    if w.get_input_purpose() == Gtk.InputPurpose.PASSWORD
                )
                self.assertFalse(password.get_visibility())
                toggle = next(
                    w
                    for w in self.widgets(dialog)
                    if isinstance(w, Gtk.CheckButton)
                    and w.get_label() == "Show password"
                )
                toggle.set_active(True)
                self.assertTrue(password.get_visibility())
                toggle.set_active(False)
                self.assertFalse(password.get_visibility())
                browse = next(
                    w
                    for w in self.widgets(dialog)
                    if isinstance(w, Gtk.Button)
                    and w.get_tooltip_text() == "Choose a local folder"
                )
                browse.clicked()
                local = next(
                    w
                    for w in entries
                    if w.get_placeholder_text() == "/mnt/nas-documents"
                )
                self.assertEqual(local.get_text(), str(chosen_folder))
                observed.append("editor")
                return Gtk.ResponseType.CANCEL

            def inspect_window():
                window = next(
                    w
                    for w in Gtk.Window.list_toplevels()
                    if w.get_title() == "Netmount"
                )
                self.assertTrue(window.get_visible())
                text = [
                    w.get_text()
                    for w in self.widgets(window)
                    if isinstance(w, Gtk.Label)
                ]
                self.assertIn("Your files, within reach", text)
                add = next(
                    w
                    for w in self.widgets(window)
                    if isinstance(w, Gtk.Button)
                    and w.get_label() == "＋  Add connection"
                )
                window.busy = True
                add.clicked()
                window.busy = False
                self.assertEqual(observed, ["editor"])
                self.assertEqual(manager.profiles, [])
                # An active operation must not be dismissed by its polkit prompt.
                window.busy = True
                with patch.object(window, "close") as close:
                    window.dismiss_unfocused()
                    close.assert_not_called()
                window.busy = False
                # Another NAS dialog owning focus also keeps the manager open.
                with (
                    patch.object(window, "is_active", return_value=True),
                    patch.object(window, "close") as close,
                ):
                    window.dismiss_unfocused()
                    close.assert_not_called()
                # Clicking outside all NAS windows dismisses the manager.
                with (
                    patch.object(window, "is_active", return_value=False),
                    patch.object(window, "close") as close,
                ):
                    window.dismiss_unfocused()
                    close.assert_called_once()
                # Avoid Gtk.main_quit outside a main loop in this controlled render.
                window.hide()

            with (
                patch.object(nas_app, "MANAGER_LOCK_PATH", Path(home) / "manager.lock"),
                patch.object(nas_app, "PROFILE_PATH", Path(home) / "profiles.json"),
                patch("nas_manager.Manager", return_value=manager),
                patch.object(nas_app, "read_mounts", return_value=[]),
                patch.object(Gtk, "main", side_effect=inspect_window),
                patch.object(Gtk.Dialog, "run", inspect_editor),
            ):
                nas_app.main()
            for window in Gtk.Window.list_toplevels():
                if window.get_title() == "Netmount":
                    with patch.object(Gtk, "main_quit"):
                        window.destroy()


if __name__ == "__main__":
    unittest.main()
