"""Check actual Wayland manager/form bounds with isolated empty profiles."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from nas_geometry import ipc, launch_bar, popup_bounds
from test_gtk_ui import AVAILABLE, Gtk


@unittest.skipUnless(AVAILABLE, "Desktop session required")
class LivePlacementTests(unittest.TestCase):
    def test_manager_and_add_form_stay_on_screen_for_each_bar_position(self):
        from gi.repository import GLib  # type: ignore  # generated at runtime

        import nas_app

        real_main, real_run = Gtk.main, Gtk.Dialog.run
        failures = []
        for requested_edge in ("top", "bottom", "left", "right", None):
            edge = requested_edge or launch_bar(["nas_app.py"])[0]
            with self.subTest(edge=edge), tempfile.TemporaryDirectory() as directory:

                def check(title, edge=edge):
                    clients = json.loads(ipc("clients", "-j"))
                    client = next(
                        c
                        for c in clients
                        if c["pid"] == os.getpid() and c["title"] == title
                    )
                    monitor = next(
                        m
                        for m in json.loads(ipc("monitors", "-j"))
                        if m["id"] == client["monitor"]
                    )
                    expected = popup_bounds(monitor, client["size"], edge, 28)
                    self.assertEqual(tuple(client["at"]), expected[:2])
                    self.assertEqual(tuple(client["size"]), expected[2:])
                    self.assertLessEqual(client["size"][0], 460)
                    if title == "Netmount":
                        self.assertLessEqual(client["size"][0], 460)
                        self.assertLessEqual(client["size"][1], 360)

                def run_dialog(dialog):
                    def inspect():
                        try:
                            check(dialog.get_title())
                            self.assertEqual(dialog.get_property("opacity"), 1.0)
                        except Exception as exc:
                            failures.append(exc)
                        dialog.response(Gtk.ResponseType.CANCEL)
                        return False

                    GLib.timeout_add(350, inspect)
                    return real_run(dialog)

                def run_main():
                    window = next(
                        w
                        for w in Gtk.Window.list_toplevels()
                        if w.get_title() == "Netmount"
                    )
                    window.busy = True

                    def inspect():
                        try:
                            check("Netmount")
                            self.assertEqual(window.get_property("opacity"), 1.0)
                            window.new()
                            profile = dict(
                                id="demo",
                                label="Test share",
                                server="fileserver",
                                remote="shared",
                                local="/mnt/demo",
                                source="//fileserver/shared",
                            )
                            window.editor(profile, None)
                            window.editor(profile, None, login_only=True)
                        except Exception as exc:
                            failures.append(exc)
                        finally:
                            window.busy = False
                            window.destroy()
                        return False

                    GLib.timeout_add(350, inspect)
                    real_main()

                with (
                    patch.object(
                        nas_app, "PROFILE_PATH", Path(directory) / "profiles.json"
                    ),
                    patch.object(
                        nas_app, "MANAGER_LOCK_PATH", Path(directory) / "manager.lock"
                    ),
                    patch.object(
                        sys,
                        "argv",
                        ["nas_app.py", "--bar-position", edge]
                        if requested_edge
                        else ["nas_app.py"],
                    ),
                    patch.object(Gtk, "main", run_main),
                    patch.object(Gtk.Dialog, "run", run_dialog),
                    patch("nas_geometry.place_window", return_value=False),
                ):
                    nas_app.main()
        if failures:
            raise failures[0]
