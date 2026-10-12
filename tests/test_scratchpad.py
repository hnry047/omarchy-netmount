"""Regression for launching the NAS panel over an already-open scratchpad."""

import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from nas_geometry import ipc
from test_gtk_ui import AVAILABLE, Gtk


@unittest.skipUnless(AVAILABLE, "Desktop session required")
class ScratchpadTests(unittest.TestCase):
    def test_panel_does_not_join_or_hide_with_the_open_scratchpad(self):
        from gi.repository import GLib  # type: ignore  # generated at runtime

        import nas_app

        monitors = json.loads(ipc("monitors", "-j"))
        monitor = next(m for m in monitors if m.get("focused"))
        scratch = monitor["specialWorkspace"]["name"]
        if not scratch.startswith("special:"):
            self.skipTest("Open a scratchpad to exercise this regression")
        name = scratch.removeprefix("special:")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            self.skipTest("Scratchpad name is not supported by this isolated check")
        errors = []
        real_main = Gtk.main

        def run_main():
            window = next(
                w for w in Gtk.Window.list_toplevels() if w.get_title() == "Netmount"
            )

            def restore():
                current = next(
                    m
                    for m in json.loads(ipc("monitors", "-j"))
                    if m["id"] == monitor["id"]
                )
                if current["specialWorkspace"]["name"] != scratch:
                    ipc("dispatch", f'hl.dsp.workspace.toggle_special("{name}")')
                window.destroy()

            def check_after_hide():
                try:
                    self.assertTrue(
                        window.get_visible(), "Hiding scratchpad must not dismiss NAS"
                    )
                    current = next(
                        m
                        for m in json.loads(ipc("monitors", "-j"))
                        if m["id"] == monitor["id"]
                    )
                    self.assertEqual(current["specialWorkspace"]["id"], 0)
                    client = next(
                        c
                        for c in json.loads(ipc("clients", "-j"))
                        if c["pid"] == os.getpid() and c["title"] == "Netmount"
                    )
                    self.assertGreater(client["workspace"]["id"], 0)
                    self.assertTrue(client["pinned"])
                except Exception as exc:
                    errors.append(exc)
                finally:
                    restore()
                return False

            def inspect():
                try:
                    client = next(
                        c
                        for c in json.loads(ipc("clients", "-j"))
                        if c["pid"] == os.getpid() and c["title"] == "Netmount"
                    )
                    self.assertGreater(
                        client["workspace"]["id"],
                        0,
                        "NAS inherited the scratchpad workspace",
                    )
                    self.assertTrue(client["pinned"])
                    current = next(
                        m
                        for m in json.loads(ipc("monitors", "-j"))
                        if m["id"] == monitor["id"]
                    )
                    self.assertEqual(
                        current["specialWorkspace"]["name"],
                        scratch,
                        "Opening NAS must not hide the scratchpad",
                    )
                    ipc("dispatch", f'hl.dsp.workspace.toggle_special("{name}")')
                    GLib.timeout_add(350, check_after_hide)
                except Exception as exc:
                    errors.append(exc)
                    restore()
                return False

            GLib.timeout_add(350, inspect)
            real_main()

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(nas_app, "PROFILE_PATH", Path(directory) / "profiles.json"),
            patch.object(
                nas_app, "MANAGER_LOCK_PATH", Path(directory) / "manager.lock"
            ),
            patch.object(Gtk, "main", run_main),
        ):
            nas_app.main()
        if errors:
            raise errors[0]
